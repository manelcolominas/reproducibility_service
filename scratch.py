import requests

url = "https://zenodo.org/records/22228540/files/COMPSs_RO-Crate_20260811_160903.zip"
output = "COMPSs_RO-Crate_20260811_160903.zip"

with requests.get(url, stream=True) as r:
    r.raise_for_status()
    with open(output, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1 MB
            if chunk:
                f.write(chunk)

print(f"Downloaded: {output}")