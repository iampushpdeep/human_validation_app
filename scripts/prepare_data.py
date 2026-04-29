#!/usr/bin/env python3
"""
Data preparation script: Convert raw cluster data to Label Studio format.

Converts {label}_metadata_with_probs.jsonl format to Label Studio import format.
"""

import json
import argparse
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict


def load_jsonl(filepath: str) -> List[Dict[str, Any]]:
    """Load JSONL file."""
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def group_by_cluster(data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group items by cluster."""
    clusters = defaultdict(list)
    for item in data:
        cluster_id = item.get('cid', 'unknown')
        clusters[cluster_id].append(item)
    return clusters


def sample_examples(cluster_items: List[Dict[str, Any]], n_samples: int = 30) -> List[Dict[str, Any]]:
    """
    Sample examples from cluster, mixing typical and edge cases.
    
    Strategy:
    - Sort by cluster_probability to identify centroid vs edge cases
    - Take mix of high-confidence (typical) and lower-confidence (edge cases)
    """
    if len(cluster_items) <= n_samples:
        return cluster_items
    
    # Sort by probability
    sorted_items = sorted(cluster_items, key=lambda x: x.get('cluster_probability', 0.5), reverse=True)
    
    # Take 70% from high-confidence, 30% from edge cases
    n_typical = int(n_samples * 0.7)
    n_edge = n_samples - n_typical
    
    sampled = sorted_items[:n_typical] + sorted_items[-n_edge:]
    return sampled


def convert_to_label_studio(cluster_data: Dict[str, List[Dict[str, Any]]], 
                           n_samples: int = 30) -> List[Dict[str, Any]]:
    """
    Convert cluster data to Label Studio import format.
    
    Returns list of tasks ready for Label Studio import.
    """
    tasks = []
    
    for cluster_id, items in cluster_data.items():
        # Get cluster metadata (from first cluster record or from label file)
        cluster_name = items[0].get('cluster_name', f"Cluster {cluster_id}")
        baseline_label = items[0].get('baseline_label', "Baseline")
        
        # Sample examples
        sampled = sample_examples(items, n_samples=n_samples)
        
        # Calculate stats
        avg_probability = sum(item.get('cluster_probability', 0.5) for item in items) / len(items)
        
        # Build task
        task = {
            "id": cluster_id,
            "data": {
                "cluster_name": cluster_name,
                "cluster_id": cluster_id,
                "total_samples": len(items),
                "avg_cluster_probability": f"{avg_probability:.3f}",
                "baseline_label": baseline_label,
                "examples": sampled,
            }
        }
        
        tasks.append(task)
    
    return tasks


def save_label_studio_format(tasks: List[Dict[str, Any]], output_path: str):
    """Save tasks in Label Studio JSON format."""
    with open(output_path, 'w') as f:
        json.dump(tasks, f, indent=2)
    print(f"✅ Saved {len(tasks)} tasks to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert cluster data to Label Studio format"
    )
    parser.add_argument(
        "--input",
        type=str,
        default="data/dummy_clusters.jsonl",
        help="Input JSONL file (default: data/dummy_clusters.jsonl)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/label_studio_import.json",
        help="Output JSON file for Label Studio import"
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=30,
        help="Number of examples per cluster (default: 30)"
    )
    
    args = parser.parse_args()
    
    # Load
    print(f"📖 Loading data from {args.input}...")
    cluster_data = load_jsonl(args.input)
    
    # Group
    print("🔄 Grouping items by cluster...")
    grouped = group_by_cluster(cluster_data)
    print(f"   Found {len(grouped)} clusters")
    
    # Convert
    print(f"🔀 Converting to Label Studio format (sampling {args.samples} examples per cluster)...")
    tasks = convert_to_label_studio(grouped, n_samples=args.samples)
    
    # Save
    save_label_studio_format(tasks, args.output)
    
    # Print summary
    print(f"\n📊 Summary:")
    print(f"   Total clusters: {len(tasks)}")
    print(f"   Examples per cluster: {args.samples}")
    print(f"   Total items to annotate: {len(tasks)} clusters × ~5 annotators")
    

if __name__ == "__main__":
    main()
