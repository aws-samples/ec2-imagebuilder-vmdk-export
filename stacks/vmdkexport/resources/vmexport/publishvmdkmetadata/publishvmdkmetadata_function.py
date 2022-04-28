##################################################
## Publish VMDK export values
##################################################

import os
import boto3
from botocore.exceptions import ClientError
import json
import logging
from datetime import datetime
from jinja2 import Environment, BaseLoader, select_autoescape

# set logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# inline email template
email_template="""
Hi there!

Your AMI has been exported to VMDK format successfully.

AMI: {{ params['ami_id'] }} has been exported to {{ params['vmdk_id'] }} on {{ params['export_date'] }}.

Below are some key details of the VDMK export process:

    * AMI Id: {{ params['ami_id'] }}
    * AMI Name: {{ params['ami_name'] }}
    * VMDK id: {{ params['vmdk_id'] }}

The VMDK file can be downloaded from the AWS console at the following S3 Bucket path:

    {{ params['s3_image_path'] }}

That's all folks!
"""

def put_ssm_parameter(ssm_param_name: str, ssm_param_val: str):
    logger.debug(f"Writing {ssm_param_name} with the value: {ssm_param_val} to ssm")
    ssm_client = boto3.client('ssm')
    parameter = ssm_client.put_parameter(Name=ssm_param_name, Value=ssm_param_val, Type='String', Overwrite=True)
    return parameter['Version']

def sns_publish_message(sns_topic, params):
    template = Environment(
        loader=BaseLoader(),
        autoescape=select_autoescape(['html', 'xml'])
    ).from_string(email_template)
    message = template.render(params=params)

    sns_client = boto3.client('sns')
    response = sns_client.publish(
        TopicArn=sns_topic,
        Message=message,
        Subject="VMDK Export is ready"
    )
    return response

def lambda_handler(event, context):
    # print the event details
    logger.debug(json.dumps(event, indent=2))

    # get env vars
    pipeline_name = os.environ['PIPELINE_NAME']
    recipie_version = os.environ['RECIPIE_VERSION']
    sns_topic = os.environ['SNS_TOPIC']

    # grab the event parameters
    ami_id = event["ami_id"]
    ami_name = event["ami_name"]
    export_image_task_id = event["export_image_task_id"]
    logger.debug(f"ami_id = {ami_id}")
    logger.debug(f"ami_name = {ami_name}")
    logger.debug(f"export_image_task_id = {export_image_task_id}")

    # get the ami export task
    ec2_client = boto3.client('ec2')
    response = ec2_client.describe_export_image_tasks(
        ExportImageTaskIds=[
            export_image_task_id
        ]
    )

    ami_export_task = None

    if len(response['ExportImageTasks']) > 0:
        for export_task in response['ExportImageTasks']:
            if export_task['ExportImageTaskId'] == export_image_task_id:
                logger.info(f"Got task id match: {export_task['ExportImageTaskId']}")
                ami_export_task = export_task
                break

    image_id=f"{ami_export_task['ExportImageTaskId']}.vmdk"
    export_bucket=f"{ami_export_task['S3ExportLocation']['S3Bucket']}"
    export_bucket_prefix=f"{ami_export_task['S3ExportLocation']['S3Prefix']}"
    image_path=f"s3://{export_bucket}/{export_bucket_prefix}{image_id}"

    logger.debug(f"image_id = {image_id}")
    logger.debug(f"export_bucket = {export_bucket}")
    logger.debug(f"export_bucket_prefix = {export_bucket_prefix}")
    logger.debug(f"image_path = {image_path}")

    ssm_path=f"/{pipeline_name}/{recipie_version}"
    put_ssm_parameter(f"{ssm_path}/export/status", "Success")
    put_ssm_parameter(f"{ssm_path}/export/ExportAMI", f"{image_id}")
    put_ssm_parameter(f"{ssm_path}/export/Bucket", f"{export_bucket}")
    put_ssm_parameter(f"{ssm_path}/export/ImagePath", f"{image_path}")
    put_ssm_parameter(f"{ssm_path}/export/Date", f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

    params = {}
    params['ami_id'] = ami_id
    params['ami_name'] = ami_name
    params['vmdk_id'] = image_id
    params['s3_image_path'] = image_path
    params['export_date'] = f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"

    sns_publish_message(sns_topic, params)
    
    return {
        'statusCode': 200,
        'body': event,
        'headers': {'Content-Type': 'application/json'}
    }