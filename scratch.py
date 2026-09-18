import requests

from services.import_crate import filename_from_http_response

url = "https://zenodo.org/records/22228540/files/COMPSs_RO-Crate_20260811_160903.zip"

response = requests.get(url, stream=True)
response.raise_for_status()
downloaded_filename = filename_from_http_response(response)

file = open(downloaded_filename, "wb")
for chunk in response.iter_content(chunk_size=1024 * 1024):  # 1 MB
    if chunk:
        file.write(chunk)
file.close()

print(f"Downloaded: {downloaded_filename}")