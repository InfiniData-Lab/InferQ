import os
import sys
from azure.storage.blob import ContainerClient

def download_blobs(container_url, download_path):
    """
    Downloads all blobs from a public container anonymously.
    """
    print(f"Connecting to container: {container_url}")
    
    # Create a ContainerClient using the container URL directly (anonymous access)
    # credential=None implies anonymous public read access
    try:
        container_client = ContainerClient.from_container_url(container_url, credential=None)
    except Exception as e:
        print(f"Error creating client: {e}")
        return

    # Create download directory if it doesn't exist
    if not os.path.exists(download_path):
        try:
            os.makedirs(download_path)
            print(f"Created download directory: {download_path}")
        except OSError as e:
            print(f"Error creating directory {download_path}: {e}")
            return

    print("Listing blobs...")
    try:
        blobs = container_client.list_blobs()
        count = 0
        for blob in blobs:
            blob_name = blob.name
            local_path = os.path.join(download_path, blob_name)
            
            # Handle nested blobs (directories)
            local_dir = os.path.dirname(local_path)
            if local_dir and not os.path.exists(local_dir):
                os.makedirs(local_dir)

            print(f"Downloading: {blob_name}")
            
            try:
                blob_client = container_client.get_blob_client(blob)
                with open(local_path, "wb") as download_file:
                    download_stream = blob_client.download_blob()
                    download_file.write(download_stream.readall())
                count += 1
            except Exception as e:
                print(f"Failed to download {blob_name}: {e}")
        
        print(f"\nDownload complete. Total files: {count}")
            
    except Exception as e:
        print(f"Error listing or processing blobs: {e}")
        print("Ensure the container URL is correct and allows public anonymous access.")

if __name__ == "__main__":
    # URL provided by user
    CONTAINER_URL = "https://inferqstorage.blob.core.windows.net/circuits"
    
    # Default download location relative to script execution or fixed path
    # Using a folder in the current directory or user specified
    DOWNLOAD_TARGET = "downloaded_circuits_public"
    
    print(f"Target Container: {CONTAINER_URL}")
    print(f"Target Directory: {os.path.abspath(DOWNLOAD_TARGET)}")
    
    download_blobs(CONTAINER_URL, DOWNLOAD_TARGET)
