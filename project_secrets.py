from google.cloud import secretmanager
import os

def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    project_id = 'causmos' #os.getenv('GOOGLE_CLOUD_PROJECT')
    name = client.secret_path(project_id, secret_id)
    name = f"{name}/versions/latest"

    response = client.access_secret_version(request={"name": name})
    secret = response.payload.data.decode("UTF-8")
    return secret