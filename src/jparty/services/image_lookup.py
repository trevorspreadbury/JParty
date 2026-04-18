import requests


def search_wikimedia_image(query):
    url = "https://en.wikipedia.org/w/api.php"
    headers = {"User-Agent": "J-NoChance/0.1 (trevorspreadbury@gmail.com)"}
    params = {
        "action": "query",
        "format": "json",
        "prop": "pageimages",
        "titles": query,
        "pithumbsize": 500,
    }
    response = requests.get(url, params=params, headers=headers)
    if response.status_code == 200:
        data = response.json()
        pages = data.get("query", {}).get("pages", {})
        for page_data in pages.values():
            if "thumbnail" in page_data:
                return page_data["thumbnail"]["source"]
        return "No image found."
    return f"Error: {response.status_code}"
