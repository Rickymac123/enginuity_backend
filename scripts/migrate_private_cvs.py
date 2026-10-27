"""Copy existing CVs to the private bucket before updating their authenticated links.

Default: report only. Apply after a database backup and private-bucket access check:
python -m scripts.migrate_private_cvs --apply
Remove verified public copies with the separate --remove-public-copy option.
Run during a maintenance window so uploads cannot race the migration.
"""
import argparse
import re
from botocore.exceptions import ClientError
from sqlmodel import Session, select
from app.db import engine
from app.storage.r2 import r2_client, bucket_name, private_bucket_name, public_base_url
from models.talent import Talent
from auth.models import User


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--remove-public-copy',action='store_true')
    args=parser.parse_args()
    if args.remove_public_copy and not args.apply:
        parser.error('--remove-public-copy requires --apply')
    source=bucket_name();destination=private_bucket_name();s3=r2_client()
    with Session(engine) as session:
        for talent in session.exec(select(Talent)).all():
            if talent.cv_storage_key:
                # A previous run may have committed the link before cleanup.
                if args.remove_public_copy and re.fullmatch(r'legacy/cvs/user_\d+\.(pdf|docx)', talent.cv_storage_key):
                    key = talent.cv_storage_key[len('legacy/'):]
                    try:
                        original = s3.head_object(Bucket=source, Key=key)
                    except ClientError as error:
                        if error.response['Error']['Code'] in {'404', 'NoSuchKey', 'NotFound'}:
                            continue
                        raise
                    copied = s3.head_object(Bucket=destination, Key=talent.cv_storage_key)
                    if copied['ContentLength'] != original['ContentLength'] or copied['ETag'] != original['ETag']:
                        raise RuntimeError('Copy verification failed; original remains untouched')
                    s3.delete_object(Bucket=source, Key=key)
                continue
            prefix=public_base_url().rstrip('/')+'/'
            if not talent.cv_url or not talent.cv_url.startswith(prefix):
                continue
            key=talent.cv_url[len(prefix):]
            if not re.fullmatch(r'cvs/user_\d+\.(pdf|docx)',key):
                raise RuntimeError(f'Unexpected legacy CV key for talent {talent.id}; inspect manually')
            private_key=f'legacy/{key}'
            print(f'Talent {talent.id}: '+('migrating' if args.apply else 'ready to migrate'))
            if not args.apply:continue
            original=s3.head_object(Bucket=source,Key=key)
            s3.copy_object(Bucket=destination,Key=private_key,CopySource={'Bucket':source,'Key':key},
                MetadataDirective='REPLACE',ContentType=original['ContentType'],
                ContentDisposition='attachment',CacheControl='private, no-store')
            copied=s3.head_object(Bucket=destination,Key=private_key)
            if copied['ContentLength']!=original['ContentLength'] or copied['ETag']!=original['ETag']:
                raise RuntimeError('Copy verification failed; original remains untouched')
            talent.cv_storage_key=private_key;talent.cv_url=f'/api/uploads/cv/{talent.id}'
            session.add(talent);session.commit()
            if args.remove_public_copy:s3.delete_object(Bucket=source,Key=key)
    print('Review any orphaned cvs/ objects in the public bucket before launch; do not delete without retaining a private copy.')

if __name__=='__main__':main()
