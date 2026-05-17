import requests

def fetch_oembed(post_url):
    endpoint = "https://api.instagram.com/oembed/"
    params = {"url": post_url}

    r = requests.get(endpoint, params=params, timeout=10)
    r.raise_for_status()

    return r.json()
