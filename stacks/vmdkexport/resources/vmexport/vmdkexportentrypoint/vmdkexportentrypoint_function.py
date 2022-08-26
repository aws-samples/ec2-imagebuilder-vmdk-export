#!/usr/bin/env python

"""
    vmdkexportentrypoint_function.py:
    AWS Step Functions State Machine Lambda Handler which 
    serves as the entry point to the AMI -> VMDK export process.
"""

import json
import logging


def lambda_handler(event, context):
    # set logging
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # print the event details
    logger.debug(json.dumps(event, indent=2))

    image_build_version_arn = event["image_build_version_arn"]

    if image_build_version_arn is not None:
        return {
            'statusCode': 200,
            'body': event,
            'headers': {'Content-Type': 'application/json'}
        }
    else:
        raise ValueError("image_build_version_arn is not present in request")
