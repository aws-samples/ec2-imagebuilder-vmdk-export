#!/usr/bin/env python

"""
    publishamimetadata_function.py:
    AWS Step Functions State Machine Lambda Handler which 
    publishes AMI creation metadata to SSM parameter store.
"""

import json
import logging
import os
from datetime import datetime

import boto3

# set logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

imagebuilder_client = boto3.client('imagebuilder')

def put_ssm_parameter(ssm_param_name: str, ssm_param_val: str):
    logger.debug(f"Writing {ssm_param_name} with the value: {ssm_param_val} to ssm")
    ssm_client = boto3.client('ssm')
    parameter = ssm_client.put_parameter(Name=ssm_param_name, Value=ssm_param_val, Type='String', Overwrite=True)
    return parameter['Version']

def lambda_handler(event, context):
    # print the event details
    logger.debug(json.dumps(event, indent=2))

    # get env vars
    pipeline_name = os.environ['PIPELINE_NAME']
    recipie_version = os.environ['RECIPIE_VERSION']

    # grab the ami id
    image_build_version_arn = event["image_build_version_arn"]
    imagebuilder_client = boto3.client('imagebuilder')
    response = imagebuilder_client.get_image(
        imageBuildVersionArn=image_build_version_arn
    )
    ami_id = response['image']['outputResources']['amis'][0]['image']
    ami_name = response['image']['outputResources']['amis'][0]['name']
    logger.info(f"ami_id = {ami_id}")
    logger.info(f"ami_name = {ami_name}")

    ssm_path=f"/{pipeline_name}/{recipie_version}"
    put_ssm_parameter(f"{ssm_path}/Build", "Success")
    put_ssm_parameter(f"{ssm_path}/BuildTimeStamp", f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    put_ssm_parameter(f"{ssm_path}/AMI_ID", f"{ami_id}")
    put_ssm_parameter(f"{ssm_path}/AMI_NAME", f"{ami_name}")

    event["ami_id"] = ami_id
    event["ami_name"] = ami_name
    
    return {
        'statusCode': 200,
        'body': event,
        'headers': {'Content-Type': 'application/json'}
    }
