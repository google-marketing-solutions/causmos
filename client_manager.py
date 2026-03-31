# Copyright 2024 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Client Management Module for Multi-Client Dashboard.

This module provides CRUD operations for managing multiple clients
and their associated causal impact analyses.
"""

from datetime import datetime
from firebase_admin import firestore
from typing import Dict, List, Optional
import firebase_admin

# Initialize Firestore client
try:
    db = firestore.Client()
except:
    # If already initialized in fs_storage.py
    from fs_storage import db

CLIENTS_COLLECTION = 'clients'
ANALYSES_COLLECTION = 'analyses'


def create_client(user_id: str, client_name: str, client_info: Optional[Dict] = None) -> str:
    """Create a new client record.

    Args:
        user_id: The ID of the user creating the client.
        client_name: The name of the client.
        client_info: Optional dictionary with additional client information.

    Returns:
        The client document ID.
    """
    client_data = {
        'name': client_name,
        'user_id': user_id,
        'created_at': firestore.SERVER_TIMESTAMP,
        'updated_at': firestore.SERVER_TIMESTAMP,
        'active': True,
    }

    if client_info:
        client_data.update(client_info)

    doc_ref = db.collection(CLIENTS_COLLECTION).document()
    doc_ref.set(client_data)

    return doc_ref.id


def get_client(client_id: str) -> Optional[Dict]:
    """Get a client by ID.

    Args:
        client_id: The client document ID.

    Returns:
        Client data as dictionary or None if not found.
    """
    doc_ref = db.collection(CLIENTS_COLLECTION).document(client_id)
    doc = doc_ref.get()

    if doc.exists:
        data = doc.to_dict()
        data['id'] = doc.id
        return data

    return None


def get_user_clients(user_id: str, active_only: bool = True) -> List[Dict]:
    """Get all clients for a specific user.

    Args:
        user_id: The user ID.
        active_only: If True, only return active clients.

    Returns:
        List of client dictionaries.
    """
    query = db.collection(CLIENTS_COLLECTION).where('user_id', '==', user_id)

    if active_only:
        query = query.where('active', '==', True)

    query = query.order_by('name')

    clients = []
    for doc in query.stream():
        client_data = doc.to_dict()
        client_data['id'] = doc.id
        clients.append(client_data)

    return clients


def update_client(client_id: str, updates: Dict) -> bool:
    """Update a client record.

    Args:
        client_id: The client document ID.
        updates: Dictionary of fields to update.

    Returns:
        True if successful, False otherwise.
    """
    try:
        updates['updated_at'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection(CLIENTS_COLLECTION).document(client_id)
        doc_ref.update(updates)
        return True
    except Exception as e:
        print(f"Error updating client: {e}")
        return False


def delete_client(client_id: str, hard_delete: bool = False) -> bool:
    """Delete or deactivate a client.

    Args:
        client_id: The client document ID.
        hard_delete: If True, permanently delete. If False, just mark as inactive.

    Returns:
        True if successful, False otherwise.
    """
    try:
        doc_ref = db.collection(CLIENTS_COLLECTION).document(client_id)

        if hard_delete:
            doc_ref.delete()
        else:
            doc_ref.update({
                'active': False,
                'updated_at': firestore.SERVER_TIMESTAMP
            })

        return True
    except Exception as e:
        print(f"Error deleting client: {e}")
        return False


def save_analysis(
    client_id: str,
    session_id: str,
    analysis_name: str,
    analysis_data: Dict,
    user_id: str
) -> str:
    """Save a causal impact analysis for a client.

    Args:
        client_id: The client document ID.
        session_id: The session ID used for the analysis.
        analysis_name: Name/description of the analysis.
        analysis_data: Dictionary containing analysis parameters and results.
        user_id: The user ID who created the analysis.

    Returns:
        The analysis document ID.
    """
    analysis_record = {
        'client_id': client_id,
        'session_id': session_id,
        'name': analysis_name,
        'user_id': user_id,
        'created_at': firestore.SERVER_TIMESTAMP,
        'data': analysis_data,
    }

    doc_ref = db.collection(ANALYSES_COLLECTION).document()
    doc_ref.set(analysis_record)

    return doc_ref.id


def get_client_analyses(client_id: str, limit: int = 50) -> List[Dict]:
    """Get all analyses for a specific client.

    Args:
        client_id: The client document ID.
        limit: Maximum number of analyses to return.

    Returns:
        List of analysis dictionaries, ordered by creation date (newest first).
    """
    query = (db.collection(ANALYSES_COLLECTION)
             .where('client_id', '==', client_id)
             .order_by('created_at', direction=firestore.Query.DESCENDING)
             .limit(limit))

    analyses = []
    for doc in query.stream():
        analysis_data = doc.to_dict()
        analysis_data['id'] = doc.id
        analyses.append(analysis_data)

    return analyses


def get_analysis(analysis_id: str) -> Optional[Dict]:
    """Get a specific analysis by ID.

    Args:
        analysis_id: The analysis document ID.

    Returns:
        Analysis data as dictionary or None if not found.
    """
    doc_ref = db.collection(ANALYSES_COLLECTION).document(analysis_id)
    doc = doc_ref.get()

    if doc.exists:
        data = doc.to_dict()
        data['id'] = doc.id
        return data

    return None


def get_user_recent_analyses(user_id: str, limit: int = 10) -> List[Dict]:
    """Get recent analyses across all clients for a user.

    Args:
        user_id: The user ID.
        limit: Maximum number of analyses to return.

    Returns:
        List of analysis dictionaries with client info, ordered by date.
    """
    query = (db.collection(ANALYSES_COLLECTION)
             .where('user_id', '==', user_id)
             .order_by('created_at', direction=firestore.Query.DESCENDING)
             .limit(limit))

    analyses = []
    for doc in query.stream():
        analysis_data = doc.to_dict()
        analysis_data['id'] = doc.id

        # Enrich with client name
        if 'client_id' in analysis_data:
            client = get_client(analysis_data['client_id'])
            if client:
                analysis_data['client_name'] = client.get('name', 'Unknown')

        analyses.append(analysis_data)

    return analyses


def search_clients(user_id: str, search_term: str) -> List[Dict]:
    """Search clients by name.

    Args:
        user_id: The user ID.
        search_term: The search term.

    Returns:
        List of matching client dictionaries.
    """
    # Firestore doesn't support case-insensitive search or LIKE queries
    # This is a basic implementation - for production, consider using
    # Algolia, Elasticsearch, or client-side filtering

    all_clients = get_user_clients(user_id)
    search_lower = search_term.lower()

    return [
        client for client in all_clients
        if search_lower in client.get('name', '').lower()
    ]
