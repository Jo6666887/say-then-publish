#!/usr/bin/env python3
"""Non-destructive smoke test for the local cloud-backed server."""

import hashlib

import requests


BASE_URL = "http://127.0.0.1:5173"


def get_json(path: str) -> dict:
    response = requests.get(f"{BASE_URL}{path}", timeout=20)
    response.raise_for_status()
    return response.json()


def main() -> None:
    status = get_json("/api/cloud-status")
    assert status.get("enabled") is True
    assert status.get("lastError") is None

    projects = get_json("/api/project-store").get("projects") or []
    assets_before = get_json("/api/assets").get("assets") or []
    assert projects
    assert assets_before

    referenced = next(asset for asset in assets_before if int(asset.get("referenceCount") or 0) > 0)
    asset_id = referenced["assetId"]
    asset_payload = get_json(f"/api/assets/{asset_id}")
    data_url = asset_payload.get("dataUrl") or ""
    assert data_url.startswith("data:image/")

    unconfirmed = requests.delete(f"{BASE_URL}/api/assets/{asset_id}", timeout=20)
    assert unconfirmed.status_code == 400

    protected = requests.delete(
        f"{BASE_URL}/api/assets/{asset_id}",
        json={"confirm": True, "force": False},
        timeout=20,
    )
    assert protected.status_code == 409

    assets_after = get_json("/api/assets").get("assets") or []
    assert len(assets_after) == len(assets_before)
    print(
        {
            "projects": len(projects),
            "assets": len(assets_after),
            "preview_sha256": hashlib.sha256(data_url.encode("utf-8")).hexdigest()[:12],
            "unconfirmed_delete_status": unconfirmed.status_code,
            "referenced_delete_status": protected.status_code,
        }
    )


if __name__ == "__main__":
    main()
