import os
import boto3

def r2_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )

def bucket_name() -> str:
    return os.environ["R2_BUCKET_NAME"]

def public_base_url() -> str:
    return os.environ["R2_PUBLIC_BASE_URL"].rstrip("/")