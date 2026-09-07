import os
import time
import boto3

ec2 = boto3.client("ec2")
ssm = boto3.client("ssm")

def handler(_event, _context):
    instance_id = os.environ["INSTANCE_ID"]
    state = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]["State"]["Name"]
    if state != "running":
        return {"action": "none", "state": state}
    raw = ssm.get_parameter(Name=os.environ["ACTIVITY_PARAMETER"])["Parameter"]["Value"]
    last_activity, active_jobs = (int(value) for value in raw.split(":", 1))
    idle = int(time.time()) - last_activity
    if active_jobs == 0 and last_activity > 0 and idle >= int(os.environ["IDLE_SECONDS"]):
        ec2.stop_instances(InstanceIds=[instance_id])
        return {"action": "stop", "idle_seconds": idle}
    return {"action": "none", "idle_seconds": idle, "active_jobs": active_jobs}

