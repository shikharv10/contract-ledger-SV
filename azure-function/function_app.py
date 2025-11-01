"""
Azure Function for SCITT Contract Ledger Blob Storage Backend

This Azure Function provides an HTTP endpoint for submitting contracts to blob storage
with atomic sequence number assignment using blob leases.

Environment Variables Required:
    AZURE_STORAGE_CONNECTION_STRING: Connection string for the storage account
    BLOB_CONTAINER_NAME: Name of the container (default: "contracts")

Endpoints:
    POST /api/submit - Submit a contract and get a sequence number
"""

import azure.functions as func
import json
import logging
import os
import time
from azure.storage.blob import BlobServiceClient, BlobLeaseClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Configuration
CONTAINER_NAME = os.environ.get("BLOB_CONTAINER_NAME", "contracts")
COUNTER_BLOB_NAME = "_sequence_counter.txt"


def get_next_sequence_number_atomic(container_client) -> int:
    """
    Atomically get and increment the sequence counter using blob lease.

    This ensures no two submissions get the same sequence number, even
    under concurrent access.

    Returns:
        int: The next available sequence number

    Raises:
        RuntimeError: If unable to acquire lease after retries
    """
    blob_client = container_client.get_blob_client(COUNTER_BLOB_NAME)

    # Retry parameters
    max_retries = 3
    base_delay = 1  # seconds

    for attempt in range(max_retries):
        try:
            # Ensure counter blob exists
            try:
                blob_client.get_blob_properties()
                logging.debug(f"Counter blob exists")
            except Exception:
                logging.info(f"Counter blob doesn't exist, initializing to 0")
                try:
                    # Try to create with content "0" (next will be 1)
                    blob_client.upload_blob("0", overwrite=False)
                except Exception as e:
                    # Another client might have created it simultaneously
                    logging.debug(f"Counter creation conflict (expected): {e}")
                    pass

            # Acquire lease (15-second distributed lock)
            logging.debug(f"Attempting to acquire lease (attempt {attempt + 1}/{max_retries})")
            lease = blob_client.acquire_lease(lease_duration=15)
            logging.debug(f"Lease acquired: {lease.id}")

            try:
                # Read current counter value
                download_stream = blob_client.download_blob(lease=lease)
                current_value_str = download_stream.readall().decode('utf-8').strip()
                current_value = int(current_value_str)
                logging.debug(f"Current counter value: {current_value}")

                # Calculate next sequence number
                next_sequence = current_value + 1
                logging.info(f"Allocating sequence number: {next_sequence}")

                # Write incremented value back
                blob_client.upload_blob(
                    str(next_sequence),
                    overwrite=True,
                    lease=lease
                )
                logging.debug(f"Counter incremented to {next_sequence}")

                # Return the allocated sequence number
                return next_sequence

            finally:
                # Always release lease
                try:
                    lease.release()
                    logging.debug("Lease released")
                except Exception as e:
                    logging.warning(f"Failed to release lease: {e}")

        except Exception as e:
            logging.warning(f"Lease acquisition failed (attempt {attempt + 1}/{max_retries}): {e}")

            if attempt < max_retries - 1:
                # Exponential backoff before retry
                delay = base_delay * (2 ** attempt)
                logging.debug(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                # Final attempt failed, raise error
                logging.error("Failed to acquire lease after all retries")
                raise RuntimeError(
                    f"Could not acquire sequence counter lock after {max_retries} attempts. "
                    "Another process may be holding the lock. Please try again."
                )


@app.route(route="submit", methods=["POST"])
def submit_contract(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit a contract to blob storage with atomic sequence numbering.

    Request:
        POST /api/submit
        Content-Type: application/cose
        Body: [COSE contract data]

    Response:
        200 OK
        {
            "entryId": "2.15",
            "sequenceNumber": 15,
            "timestamp": 1234567890
        }

        400 Bad Request - Invalid request
        500 Internal Server Error - Server error
    """
    logging.info('Processing contract submission')

    try:
        # Validate request
        if req.method != "POST":
            return func.HttpResponse(
                json.dumps({"error": "Method not allowed"}),
                status_code=405,
                mimetype="application/json"
            )

        # Get contract data from request body
        contract_data = req.get_body()

        if not contract_data:
            return func.HttpResponse(
                json.dumps({"error": "Empty request body"}),
                status_code=400,
                mimetype="application/json"
            )

        # Connect to blob storage
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            logging.error("AZURE_STORAGE_CONNECTION_STRING not set")
            return func.HttpResponse(
                json.dumps({"error": "Server configuration error"}),
                status_code=500,
                mimetype="application/json"
            )

        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)

        # Create container if it doesn't exist
        try:
            container_client.get_container_properties()
            logging.debug(f"Container '{CONTAINER_NAME}' exists")
        except Exception:
            logging.info(f"Creating container '{CONTAINER_NAME}'")
            try:
                container_client.create_container()
            except Exception as e:
                logging.warning(f"Container creation failed (may already exist): {e}")

        # Get next sequence number atomically
        try:
            sequence_number = get_next_sequence_number_atomic(container_client)
        except RuntimeError as e:
            logging.error(f"Failed to get sequence number: {e}")
            return func.HttpResponse(
                json.dumps({"error": "Failed to allocate sequence number", "details": str(e)}),
                status_code=500,
                mimetype="application/json"
            )

        # Generate contract ID
        contract_id = f"2.{sequence_number}"
        logging.info(f"Assigned contract ID: {contract_id}")

        # Upload contract to blob storage
        blob_name = f"{contract_id}.cose"
        blob_client = container_client.get_blob_client(blob_name)

        try:
            blob_client.upload_blob(contract_data, overwrite=False)
            logging.info(f"Uploaded contract to blob: {blob_name}")
        except Exception as e:
            logging.error(f"Failed to upload contract: {e}")
            return func.HttpResponse(
                json.dumps({"error": "Failed to upload contract", "details": str(e)}),
                status_code=500,
                mimetype="application/json"
            )

        # Return success response
        response_data = {
            "entryId": contract_id,
            "sequenceNumber": sequence_number,
            "timestamp": int(time.time())
        }

        logging.info(f"Successfully submitted contract {contract_id}")

        return func.HttpResponse(
            json.dumps(response_data),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return func.HttpResponse(
            json.dumps({"error": "Internal server error", "details": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """
    Health check endpoint.

    Response:
        200 OK
        {
            "status": "healthy",
            "container": "contracts"
        }
    """
    return func.HttpResponse(
        json.dumps({
            "status": "healthy",
            "container": CONTAINER_NAME
        }),
        status_code=200,
        mimetype="application/json"
    )
