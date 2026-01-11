import pandas as pd
from azure.data.tables import TableClient
# 💡 IMPORT THIS NEW CLASS
from azure.core.credentials import AzureNamedKeyCredential 
from typing import List, Dict, Any
from tqdm import tqdm
from itertools import islice

# using variables from .env file in same directory
from dotenv import load_dotenv
import os
load_dotenv()
STORAGE_ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT")
STORAGE_ACCOUNT_KEY = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
TABLE_NAME = "circuits" 

def fetch_table_data(account_name: str, account_key: str, table_name: str, row_limit: int = 100) -> List[Dict[str, Any]]:
    """
    Connects to Azure Table Storage, queries a specified number of entities,
    and returns the data as a list of dictionaries.
    """
    print(f"Connecting to table: {table_name}...")
    
    # Construct the endpoint URL
    table_url = f"https://{account_name}.table.core.windows.net"
    
    try:
        # Wrap the account key in the required credential object
        credential_object = AzureNamedKeyCredential(
            name=account_name,
            key=account_key
        )
        
        # Create the TableClient using the endpoint and the credential object
        table_client = TableClient(
            endpoint=table_url,
            table_name=table_name,
            credential=credential_object  # <-- Pass the object here!
        )
        
        print(f"Querying the first {row_limit} entities...")
        
        entities_generator = table_client.query_entities(
            query_filter="",
            top=row_limit
        )
        # # Use a list comprehension to efficiently fetch the top N entities
        # entities_list = [dict(entity) for i, entity in enumerate(entities_generator) if i < row_limit]
        # Use a loop with tqdm to show progress while fetching the top N entities
        entities_list = []
        for entity in tqdm(islice(entities_generator, row_limit), total=row_limit, desc="Fetching entities"):
            entities_list.append(dict(entity))
        
        print(f"Successfully fetched {len(entities_list)} entities.")
        # Let us store in a csv file
        df = pd.DataFrame(entities_list)
        df.to_csv(f"{table_name}_data{row_limit}.csv", index=False)
        print(f"Data saved to {table_name}_data{row_limit}.csv")
        return entities_list
        
    except Exception as e:
        print(f"An error occurred: {e}")
        return []

# if __name__ == "__main__":
#     fetch_table_data(STORAGE_ACCOUNT_NAME, STORAGE_ACCOUNT_KEY, TABLE_NAME, row_limit=400000)

import sys

DEFAULT_ROW_LIMIT = 414820  # whole dataset

if __name__ == "__main__":
    if len(sys.argv) > 1:
        row_limit = int(sys.argv[1])
    else:
        row_limit = DEFAULT_ROW_LIMIT
        print(f"No row_limit provided, using default: {row_limit}")

    fetch_table_data(
        STORAGE_ACCOUNT_NAME,
        STORAGE_ACCOUNT_KEY,
        TABLE_NAME,
        row_limit=row_limit
    )
