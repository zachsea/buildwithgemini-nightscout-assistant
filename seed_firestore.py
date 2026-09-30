import os
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-03-c0fc118b7249"
db = firestore.Client(project=PROJECT_ID)

def seed():
    collection_ref = db.collection("nightscout_profiles")
    
    profiles = [
        {
            "user_id": "test_user_1",
            "nightscout_url": "https://my-nightscout.herokuapp.com",
            "access_token": "api-token-123",
            "target_range_low": 70,
            "target_range_high": 180,
            "preferred_insights": "Focus on overnight stability and post-meal spikes."
        },
        {
            "user_id": "test_user_2",
            "nightscout_url": "https://nightscout-demo.fly.dev",
            "access_token": "api-token-456",
            "target_range_low": 80,
            "target_range_high": 160,
            "preferred_insights": "Highlight low glucose predictions and time in range."
        }
    ]
    
    for profile in profiles:
        doc_id = profile["user_id"]
        collection_ref.document(doc_id).set(profile)
        print(f"Seeded profile for {doc_id}")

if __name__ == "__main__":
    seed()
