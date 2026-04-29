#!/usr/bin/env python3
"""
Evaluation metrics calculation for cluster label validation.

Computes:
- Acceptance rate
- Average scores (coherence, specificity, coverage, interpretability)
- Inter-annotator agreement (Cohen's Kappa, Krippendorff's Alpha)
- Error breakdown
"""

import json
import argparse
import numpy as np
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any, Tuple


def cohens_kappa(rater1: List[int], rater2: List[int]) -> float:
    """
    Calculate Cohen's Kappa coefficient.
    Measures agreement between two raters, accounting for chance.
    
    Range: -1 to 1
    - 1.0 = perfect agreement
    - 0.6-0.8 = substantial agreement
    - 0.4-0.6 = moderate agreement
    - < 0.4 = poor agreement
    """
    n = len(rater1)
    if n != len(rater2):
        raise ValueError("Raters must have same length")
    
    # Observed agreement
    po = sum(1 for r1, r2 in zip(rater1, rater2) if r1 == r2) / n
    
    # Expected agreement by chance
    classes = set(rater1) | set(rater2)
    pe = 0
    for cls in classes:
        p1 = sum(1 for r in rater1 if r == cls) / n
        p2 = sum(1 for r in rater2 if r == cls) / n
        pe += p1 * p2
    
    # Cohen's Kappa
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    
    kappa = (po - pe) / (1 - pe)
    return kappa


def krippendorfs_alpha(annotations: List[List[int]]) -> float:
    """
    Calculate Krippendorff's Alpha for multiple raters.
    
    Args:
        annotations: List of annotation sets, each is a list of ratings
    
    Returns:
        Alpha coefficient (0 to 1, where 1 is perfect agreement)
    """
    if not annotations or len(annotations) < 2:
        return 0.0
    
    # Convert to pairable format
    n_items = len(annotations[0])
    n_raters = len(annotations)
    
    # Observed disagreement
    do = 0
    n_pairs = 0
    
    for i in range(n_items):
        for r1_idx in range(n_raters):
            for r2_idx in range(r1_idx + 1, n_raters):
                val1 = annotations[r1_idx][i]
                val2 = annotations[r2_idx][i]
                do += (val1 - val2) ** 2
                n_pairs += 1
    
    if n_pairs == 0:
        return 1.0
    
    do = do / n_pairs
    
    # Expected disagreement (by chance)
    all_values = []
    for ann in annotations:
        all_values.extend(ann)
    
    de = 0
    for i in range(len(all_values)):
        for j in range(i + 1, len(all_values)):
            de += (all_values[i] - all_values[j]) ** 2
    
    total_pairs = len(all_values) * (len(all_values) - 1) / 2
    if total_pairs == 0:
        de = 0
    else:
        de = de / total_pairs
    
    # Alpha
    if de == 0:
        return 1.0 if do == 0 else 0.0
    
    alpha = 1 - (do / de)
    return max(-1.0, min(1.0, alpha))  # Clamp to [-1, 1]


def load_label_studio_export(filepath: str) -> List[Dict[str, Any]]:
    """Load Label Studio JSON export format."""
    with open(filepath, 'r') as f:
        return json.load(f)


def process_annotations(annotations_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Process annotations from Label Studio export.
    
    Computes:
    - Acceptance rate (correct vs incorrect)
    - Average scores per dimension
    - Per-cluster scores
    - Issue breakdown
    """
    results = {
        "total_tasks": len(annotations_data),
        "total_annotations": 0,
        "acceptance_rate": 0.0,
        "average_scores": {
            "coherence": 0.0,
            "specificity": 0.0,
            "coverage": 0.0,
            "interpretability": 0.0,
        },
        "score_distribution": {
            "coherence": defaultdict(int),
            "specificity": defaultdict(int),
            "coverage": defaultdict(int),
            "interpretability": defaultdict(int),
        },
        "issue_breakdown": defaultdict(int),
        "per_cluster": {},
        "annotator_agreement": {},
    }
    
    # Group by cluster and annotator
    by_cluster = defaultdict(lambda: defaultdict(list))
    
    correct_count = 0
    score_counts = {
        "coherence": [],
        "specificity": [],
        "coverage": [],
        "interpretability": [],
    }
    
    for task in annotations_data:
        if "annotations" not in task or not task["annotations"]:
            continue
        
        cluster_id = task["data"].get("cluster_id", task.get("id", "unknown"))
        
        for annotation in task["annotations"]:
            results["total_annotations"] += 1
            result = annotation.get("result", [])
            
            # Extract ratings and feedback
            ratings = {}
            correctness = None
            issues = []
            suggested_label = None
            
            for item in result:
                if item.get("type") == "rating":
                    name = item.get("name")
                    value = item.get("value", {}).get("rating")
                    if name and value:
                        ratings[name] = value
                        score_counts[name].append(value)
                        results["score_distribution"][name][value] += 1
                
                elif item.get("type") == "choices":
                    name = item.get("name")
                    value = item.get("value", {}).get("choices", [])
                    
                    if name == "correctness" and value:
                        correctness = value[0]
                        if correctness == "correct":
                            correct_count += 1
                    
                    elif name == "issue_type" and value:
                        issues = value
            
            # Extract text annotations
            for item in result:
                if item.get("type") == "textarea":
                    name = item.get("name")
                    value = item.get("value", {}).get("text")
                    if name == "suggested_label" and value and value.strip():
                        suggested_label = value
            
            # Store by cluster and annotator
            annotator = annotation.get("completed_by", f"annotator_{len(by_cluster[cluster_id])}")
            by_cluster[cluster_id][annotator].append({
                "ratings": ratings,
                "correctness": correctness,
                "issues": issues,
                "suggested_label": suggested_label,
            })
            
            # Record issue breakdown
            for issue in issues:
                results["issue_breakdown"][issue] += 1
    
    # Calculate acceptance rate
    if results["total_annotations"] > 0:
        results["acceptance_rate"] = correct_count / results["total_annotations"]
    
    # Calculate average scores
    for dimension in results["average_scores"]:
        if score_counts[dimension]:
            results["average_scores"][dimension] = np.mean(score_counts[dimension])
    
    # Per-cluster analysis and inter-rater agreement
    for cluster_id, annotators in by_cluster.items():
        cluster_scores = {
            "annotators": len(annotators),
            "scores": {},
            "agreement": {},
            "consensus": {},
        }
        
        # Average scores per cluster
        for dimension in ["coherence", "specificity", "coverage", "interpretability"]:
            scores = []
            for annotator_anns in annotators.values():
                for ann in annotator_anns:
                    if dimension in ann["ratings"]:
                        scores.append(ann["ratings"][dimension])
            
            if scores:
                cluster_scores["scores"][dimension] = np.mean(scores)
                cluster_scores["score_distribution"] = defaultdict(int)
                for score in scores:
                    cluster_scores["score_distribution"][score] += 1
        
        # Inter-rater agreement (if multiple raters)
        if len(annotators) >= 2:
            annotator_list = list(annotators.values())
            for dimension in ["coherence", "specificity", "coverage", "interpretability"]:
                rating_sets = []
                for ann_list in annotator_list:
                    ratings = [ann["ratings"].get(dimension) for ann in ann_list 
                               if dimension in ann["ratings"]]
                    if ratings:
                        rating_sets.append(ratings)
                
                if len(rating_sets) >= 2:
                    # Use Krippendorff's Alpha
                    alpha = krippendorfs_alpha(rating_sets)
                    cluster_scores["agreement"][dimension] = alpha
        
        results["per_cluster"][cluster_id] = cluster_scores
    
    return results


def print_report(results: Dict[str, Any]):
    """Print human-readable evaluation report."""
    print("\n" + "=" * 70)
    print("CLUSTER LABEL VALIDATION REPORT")
    print("=" * 70)
    
    print(f"\n📊 OVERVIEW")
    print(f"  Total clusters evaluated: {results['total_tasks']}")
    print(f"  Total annotations: {results['total_annotations']}")
    print(f"  Average accuracy: {results['acceptance_rate']:.1%}")
    
    if results['total_annotations'] == 0:
        print("\n⚠️  No annotations found in data.")
        return
    
    print(f"\n⭐ AVERAGE SCORES (1-5 scale)")
    for dimension, score in results["average_scores"].items():
        if score > 0:
            bar = "█" * int(score) + "░" * (5 - int(score))
            print(f"  {dimension:18s}: {score:.2f}/5.0  {bar}")
    
    print(f"\n📈 SCORE DISTRIBUTION")
    for dimension, dist in results["score_distribution"].items():
        if dist:
            print(f"\n  {dimension}:")
            for rating in sorted(dist.keys()):
                count = dist[rating]
                pct = (count / sum(dist.values())) * 100 if sum(dist.values()) > 0 else 0
                print(f"    {rating}: {count:3d} ({pct:5.1f}%)")
    
    if results["issue_breakdown"]:
        print(f"\n🚨 ISSUE BREAKDOWN (when label marked incorrect)")
        total_issues = sum(results["issue_breakdown"].values())
        for issue, count in sorted(results["issue_breakdown"].items(), key=lambda x: -x[1]):
            pct = (count / total_issues * 100) if total_issues > 0 else 0
            print(f"  {issue:25s}: {count:3d} ({pct:5.1f}%)")
    
    # Inter-rater agreement
    all_agreements = []
    for cluster_id, stats in results["per_cluster"].items():
        if stats["agreement"]:
            all_agreements.extend(stats["agreement"].values())
    
    if all_agreements:
        print(f"\n🤝 INTER-RATER AGREEMENT")
        avg_agreement = np.mean(all_agreements)
        print(f"  Average Krippendorff's Alpha: {avg_agreement:.3f}")
        
        if avg_agreement >= 0.6:
            print(f"  → Substantial agreement ✅")
        elif avg_agreement >= 0.4:
            print(f"  → Moderate agreement ⚠️")
        else:
            print(f"  → Poor agreement ❌")
    
    print("\n" + "=" * 70)


def save_report(results: Dict[str, Any], output_path: str):
    """Save detailed results to JSON."""
    # Convert defaultdicts to regular dicts for JSON serialization
    def convert_dicts(obj):
        if isinstance(obj, defaultdict):
            return dict((k, convert_dicts(v)) for k, v in obj.items())
        elif isinstance(obj, dict):
            return dict((k, convert_dicts(v)) for k, v in obj.items())
        elif isinstance(obj, (list, tuple)):
            return [convert_dicts(item) for item in obj]
        else:
            return obj
    
    results_serializable = convert_dicts(results)
    
    with open(output_path, 'w') as f:
        json.dump(results_serializable, f, indent=2)
    
    print(f"\n💾 Detailed results saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Calculate label validation metrics from Label Studio export"
    )
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="Label Studio JSON export file"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="evaluation_results.json",
        help="Output JSON file for detailed results"
    )
    
    args = parser.parse_args()
    
    print(f"📖 Loading annotations from {args.input}...")
    annotations = load_label_studio_export(args.input)
    
    print(f"📊 Processing {len(annotations)} tasks...")
    results = process_annotations(annotations)
    
    print_report(results)
    save_report(results, args.output)


if __name__ == "__main__":
    main()
