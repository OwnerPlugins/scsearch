# -*- coding: utf-8 -*-
#
# TMDB Fetcher module for Enigma2
#

import requests


class TmdbFetcher:
    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

    def __init__(self, api_key="3c3efcf47c3577558812bb9d64019d65"):
        self.api_key = api_key

    def search(self, query, media_type="movie"):
        """Search for a movie or TV series and return a list of results."""
        url = f"{self.BASE_URL}/search/{media_type}"
        params = {
            "api_key": self.api_key,
            "language": "it-IT",
            "query": query
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                return None
            data = r.json()
            return data.get("results", [])
        except requests.exceptions.RequestException:
            return None

    def get_details(self, item_id, media_type="movie"):
        """Retrieve full details and format them."""
        url = f"{self.BASE_URL}/{media_type}/{item_id}"
        params = {
            "api_key": self.api_key,
            "language": "it-IT",
            "append_to_response": "videos,images"
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                return None

            details = r.json()
            return self._format_result(details, media_type)
        except requests.exceptions.RequestException:
            return None

    def _format_result(self, details, media_type="movie"):
        """Format the data into a compact dictionary."""
        titolo = details.get(
            "title") if media_type == "movie" else details.get("name")
        poster_path = details.get("poster_path")
        trailer = None

        # Retrieve trailer (YouTube)
        if "videos" in details and details["videos"].get("results"):
            for v in details["videos"]["results"]:
                if v.get("site") == "YouTube" and v.get("type") == "Trailer":
                    trailer = f"https://www.youtube.com/watch?v={v['key']}"
                    break

        result = {
            "id": details.get("id"),
            "titolo": titolo,
            "descrizione": details.get("overview"),
            "poster": f"{self.IMAGE_BASE}{poster_path}" if poster_path else None,
            "trailer": trailer,
            "data_uscita": details.get("release_date") if media_type == "movie" else details.get("first_air_date"),
            "voto": details.get("vote_average"),
            "generi": ", ".join([g.get("name", "") for g in details.get("genres", [])])
        }

        # Add fields specific to TV series
        if media_type == "tv":
            result["numero_stagioni"] = details.get("number_of_seasons", 1)
            result["numero_episodi"] = details.get("number_of_episodes", 1)

        return result
