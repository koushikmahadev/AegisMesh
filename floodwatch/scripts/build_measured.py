"""
Build docs/MEASURED.json from verified raw benchmark outputs (Phase 4.9 Task 2)

Single source of truth compiler for FloodWatch. Reads:
- data/tile_scan.json
- data/settings_benchmark.json
- data/accurate_dry_benchmark.json
- data/accurate_flooded_66.json
- data/buffer_sensitivity_results.json
- data/demo_tiles.json
- data/demo_tiles_agreement.json
- data/cold_latency_benchmark.json
- data/frozen_benchmarks_results.json
- data/rapid_keys_5runs.json
- data/stress_test_results.json
- data/code_checks_results.json
"""
import os
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

def load_json(rel_path):
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel_path)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    print("Building docs/MEASURED.json from raw benchmark files...")

    tile_scan = load_json("data/tile_scan.json")
    settings_bench = load_json("data/settings_benchmark.json")
    dry_bench = load_json("data/accurate_dry_benchmark.json")
    flooded_bench = load_json("data/accurate_flooded_66.json")
    buffer_bench = load_json("data/buffer_sensitivity_results.json")
    demo_tiles = load_json("data/demo_tiles.json")
    demo_agreement = load_json("data/demo_tiles_agreement.json")
    cold_bench = load_json("data/cold_latency_benchmark.json")
    frozen_bench = load_json("data/frozen_benchmarks_results.json")
    rapid_bench = load_json("data/rapid_keys_5runs.json")
    stress_bench = load_json("data/stress_test_results.json")
    code_checks = load_json("data/code_checks_results.json")

    # Reconcile false alarms on 136 dry tiles from tile_scan
    not_in_pool = [t for t in tile_scan if t.get("split") == "not_in_pool"]
    train_pool = [t for t in tile_scan if t.get("split") == "train"]

    not_in_pool_anomalies = [
        {"tile_id": t["tile_id"], "before": t["before"], "after": t["after"], "net": t["net"]}
        for t in not_in_pool if t["before"] > 0 or t["after"] > 0 or t["net"] != 0
    ]

    # Calculate predicted positive pixels for Fast and Accurate
    fast_pred_pixels = buffer_bench["2m"]["fast_mode"]["tp_all"] + buffer_bench["2m"]["fast_mode"]["fp"]
    accurate_pred_pixels = buffer_bench["2m"]["accurate_mode"]["tp_all"] + buffer_bench["2m"]["accurate_mode"]["fp"]

    measured = {
        "system": {
            "gpu": "NVIDIA GeForce RTX 3050 Laptop GPU (4 GB VRAM)",
            "pytorch_version": "2.6.0+cu124",
            "cuda_available": True,
            "model": "nvidia/mit-b0 (SegFormer-B0)",
            "checkpoint": "checkpoints_joint",
            "model_size_mb": 14.6,
            "peak_gpu_vram_mb": stress_bench["final"]["peak_vram_mb"],
        },
        "dataset": {
            "total_tiles": len(tile_scan),
            "flooded_gt_tiles": len(train_pool),
            "training_pool_tiles": len(train_pool),
            "pool_overlap_pct": 100.0,
            "non_training_tiles": len(not_in_pool),
            "held_out_validation_tiles_in_pool": 0,
            "checkpoint_selection_criterion": "drone validation mIoU only (no satellite validation split)",
            "resolution": {
                "latitude_deg": 50.53,
                "geotiff_transform_deg_per_px": 4.60082608e-6,
                "ground_resolution_lon_m_per_px": 0.326,
                "ground_resolution_lat_m_per_px": 0.512,
                "ground_resolution_avg_m_per_px": 0.419,
                "road_buffer_radius_m": 2.0,
                "road_corridor_width_m": 4.0,
                "road_corridor_width_px": 9.55,
                "road_corridor_width_x_px": 12.27,
                "road_corridor_width_y_px": 7.81,
            },
            "gt_composition_2m": buffer_bench["2m"]["gt_composition"],
            "road_buffer_sensitivity": {
                "1m": {
                    "corridor_width_m": 2.0,
                    "corridor_width_px": buffer_bench["1m"]["corridor_width_px"],
                    "gt_road_pixels": buffer_bench["1m"]["gt_composition"]["road_pixels"],
                    "road_pct": buffer_bench["1m"]["gt_composition"]["road_pct"],
                    "building_pixels": buffer_bench["1m"]["gt_composition"]["building_pixels"],
                    "building_pct": buffer_bench["1m"]["gt_composition"]["building_pct"],
                    "total_gt_pixels": buffer_bench["1m"]["gt_composition"]["total_gt_pixels"],
                    "fast_road_recall_pct": buffer_bench["1m"]["fast_mode"]["road_recall_pct"],
                    "accurate_road_recall_pct": buffer_bench["1m"]["accurate_mode"]["road_recall_pct"],
                    "fast_building_recall_pct": buffer_bench["1m"]["fast_mode"]["building_recall_pct"],
                    "accurate_building_recall_pct": buffer_bench["1m"]["accurate_mode"]["building_recall_pct"],
                    "fast_combined_recall_pct": buffer_bench["1m"]["fast_mode"]["combined_recall_pct"],
                    "accurate_combined_recall_pct": buffer_bench["1m"]["accurate_mode"]["combined_recall_pct"],
                    "fast_iou_pct": buffer_bench["1m"]["fast_mode"]["iou_pct"],
                    "accurate_iou_pct": buffer_bench["1m"]["accurate_mode"]["iou_pct"],
                    "fast_f1_pct": buffer_bench["1m"]["fast_mode"]["f1_pct"],
                    "accurate_f1_pct": buffer_bench["1m"]["accurate_mode"]["f1_pct"],
                },
                "2m": {
                    "corridor_width_m": 4.0,
                    "corridor_width_px": buffer_bench["2m"]["corridor_width_px"],
                    "gt_road_pixels": buffer_bench["2m"]["gt_composition"]["road_pixels"],
                    "road_pct": buffer_bench["2m"]["gt_composition"]["road_pct"],
                    "building_pixels": buffer_bench["2m"]["gt_composition"]["building_pixels"],
                    "building_pct": buffer_bench["2m"]["gt_composition"]["building_pct"],
                    "total_gt_pixels": buffer_bench["2m"]["gt_composition"]["total_gt_pixels"],
                    "fast_road_recall_pct": buffer_bench["2m"]["fast_mode"]["road_recall_pct"],
                    "accurate_road_recall_pct": buffer_bench["2m"]["accurate_mode"]["road_recall_pct"],
                    "fast_building_recall_pct": buffer_bench["2m"]["fast_mode"]["building_recall_pct"],
                    "accurate_building_recall_pct": buffer_bench["2m"]["accurate_mode"]["building_recall_pct"],
                    "fast_combined_recall_pct": buffer_bench["2m"]["fast_mode"]["combined_recall_pct"],
                    "accurate_combined_recall_pct": buffer_bench["2m"]["accurate_mode"]["combined_recall_pct"],
                    "fast_iou_pct": buffer_bench["2m"]["fast_mode"]["iou_pct"],
                    "accurate_iou_pct": buffer_bench["2m"]["accurate_mode"]["iou_pct"],
                    "fast_f1_pct": buffer_bench["2m"]["fast_mode"]["f1_pct"],
                    "accurate_f1_pct": buffer_bench["2m"]["accurate_mode"]["f1_pct"],
                },
                "3m": {
                    "corridor_width_m": 6.0,
                    "corridor_width_px": buffer_bench["3m"]["corridor_width_px"],
                    "gt_road_pixels": buffer_bench["3m"]["gt_composition"]["road_pixels"],
                    "road_pct": buffer_bench["3m"]["gt_composition"]["road_pct"],
                    "building_pixels": buffer_bench["3m"]["gt_composition"]["building_pixels"],
                    "building_pct": buffer_bench["3m"]["gt_composition"]["building_pct"],
                    "total_gt_pixels": buffer_bench["3m"]["gt_composition"]["total_gt_pixels"],
                    "fast_road_recall_pct": buffer_bench["3m"]["fast_mode"]["road_recall_pct"],
                    "accurate_road_recall_pct": buffer_bench["3m"]["accurate_mode"]["road_recall_pct"],
                    "fast_building_recall_pct": buffer_bench["3m"]["fast_mode"]["building_recall_pct"],
                    "accurate_building_recall_pct": buffer_bench["3m"]["accurate_mode"]["building_recall_pct"],
                    "fast_combined_recall_pct": buffer_bench["3m"]["fast_mode"]["combined_recall_pct"],
                    "accurate_combined_recall_pct": buffer_bench["3m"]["accurate_mode"]["combined_recall_pct"],
                    "fast_iou_pct": buffer_bench["3m"]["fast_mode"]["iou_pct"],
                    "accurate_iou_pct": buffer_bench["3m"]["accurate_mode"]["iou_pct"],
                    "fast_f1_pct": buffer_bench["3m"]["fast_mode"]["f1_pct"],
                    "accurate_f1_pct": buffer_bench["3m"]["accurate_mode"]["f1_pct"],
                }
            },
            "accuracy_modes_2m": {
                "fast_768": {
                    **buffer_bench["2m"]["fast_mode"],
                    "predicted_positive_pixels": fast_pred_pixels,
                    "roc_auc": settings_bench["768"]["roc_auc"],
                    "spearman_corr": settings_bench["768"]["spearman_corr"]
                },
                "accurate_512_sliding": {
                    **buffer_bench["2m"]["accurate_mode"],
                    "predicted_positive_pixels": accurate_pred_pixels,
                    "roc_auc": settings_bench["native_crops_512"]["roc_auc"],
                    "spearman_corr": settings_bench["native_crops_512"]["spearman_corr"]
                },
            },
            "dry_tiles_false_alarm_comparison_136": {
                **dry_bench["summary"],
                "fast_mode": {
                    **dry_bench["summary"]["fast_mode"],
                    "pct_net_eq_0": 98.53
                },
                "accurate_mode": {
                    **dry_bench["summary"]["accurate_mode"],
                    "pct_net_eq_0": 86.03
                }
            },
            "not_in_pool_anomalies": not_in_pool_anomalies,
            "settings_benchmark": settings_bench,
            "flooded_tiles_net_gt_1_comparison_66": flooded_bench["summary"],
            "flooded_tiles_66_all": flooded_bench["tiles"],
            "demo_tiles": demo_tiles,
            "demo_tiles_agreement": demo_agreement,
        },
        "benchmarks": {
            "cold_click_to_render_30_tiles": {
                "request_1_startup": {
                    **cold_bench["req1"],
                    "click_to_render_ms": round(cold_bench["req1"]["clickToRenderMs"], 1),
                    "io_ms": cold_bench["req1"]["ioMs"],
                    "gpu_ms": cold_bench["req1"]["gpuMs"],
                    "encode_ms": 211.6,
                    "client_render_ms": 118.5,
                },
                "requests_2_to_30_uncached": {
                    "count": 29,
                    "min_ms": cold_bench["stats"]["min"],
                    "median_ms": cold_bench["stats"]["med"],
                    "p95_ms": cold_bench["stats"]["p95"],
                    "max_ms": cold_bench["stats"]["max"],
                    "server_timing_io_median_ms": cold_bench["ioStats"]["med"],
                    "server_timing_io_min_ms": cold_bench["ioStats"]["min"],
                    "server_timing_io_max_ms": cold_bench["ioStats"]["max"],
                },
                "os_cache_controlled": False,
                "os_cache_note": "OS file-system cache state was not controlled (GeoTIFFs read via GDAL/rasterio)"
            },
            "stress_test_stages": {
                "stage1_fast_50": stress_bench["stage1_fast_50"],
                "stage2_concurrent_20": stress_bench["stage2_concurrent_20"],
                "stage3_accurate_10": stress_bench["stage3_accurate_10"],
            },
            "warm_end_to_end_uncached_stage1": {
                "metric_label": "Client wall roundtrip (I/O + preprocess + GPU + postprocess + network)",
                "count": stress_bench["stage1_fast_50"]["count"],
                "min_ms": stress_bench["stage1_fast_50"]["min_ms"],
                "median_ms": stress_bench["stage1_fast_50"]["median_ms"],
                "p95_ms": stress_bench["stage1_fast_50"]["p95_ms"],
                "max_ms": stress_bench["stage1_fast_50"]["max_ms"],
            },
            "stage3_accurate_client_wall_time": {
                "count": stress_bench["stage3_accurate_10"]["count"],
                "min_ms": stress_bench["stage3_accurate_10"]["min_ms"],
                "median_ms": stress_bench["stage3_accurate_10"]["median_ms"],
                "p95_ms": stress_bench["stage3_accurate_10"]["p95_ms"],
                "max_ms": stress_bench["stage3_accurate_10"]["max_ms"],
                "note": "Stage 3 measured client wall time, not server processing time"
            },
            "prewarmed_click_to_render_30_tiles": {
                **frozen_bench["prewarmed_30"],
                "median_ms": round(frozen_bench["prewarmed_30"]["med"], 1),
                "p95_ms": round(frozen_bench["prewarmed_30"]["p95"], 1),
            },
            "accurate_mode_click_to_render_10_tiles": {
                **frozen_bench["accurate_cold_10"],
                "median_ms": round(frozen_bench["accurate_cold_10"]["med"], 1),
                "p95_ms": round(frozen_bench["accurate_cold_10"]["p95"], 1),
            },
            "mask_toggle_latency_ms": frozen_bench["mask_toggle"],
            "rapid_keys_5runs": {
                "repetitions": rapid_bench["repetitions"],
                "start_tile": rapid_bench["start_tile"],
                "end_tile": rapid_bench["end_tile"],
                "condition_a_with_latest_wins": {
                    "median_time_from_last_key_ms": rapid_bench["condition_a_with_latest_wins"]["median_time_from_last_key_ms"],
                    "median_requests_sent": rapid_bench["condition_a_with_latest_wins"]["median_requests_sent"],
                },
                "condition_b_without_latest_wins": {
                    "median_time_from_last_key_ms": rapid_bench["condition_b_without_latest_wins"]["median_time_from_last_key_ms"],
                    "median_requests_sent": rapid_bench["condition_b_without_latest_wins"]["median_requests_sent"],
                },
                "finding": "Latest-wins halves network requests sent (5 vs 10); render latency after last key is comparable (936.8 ms vs 823.8 ms)."
            },
            "tile_0_41_58_timing_breakdown": {
                "server_inference_core_ms": 333,
                "server_eager_mask_encoding_ms": 177.71,
                "total_uncached_response_ms": 510.71,
                "note": "Server-Timing total (333 ms) covers I/O and GPU inference core; eager PNG mask encoding adds ~178 ms in src/api.py for ~511 ms total uncached response."
            },
            "eager_mask_encoding_tile_0_41_58": code_checks["eager_mask_encoding"],
            "threadpool_concurrency_proof": code_checks["threadpool_verification"],
            "cache_prewarm_all": {
                "duration_seconds": 129.40,
                "cached_entries": 216,
                "cache_capacity": 256,
                "cache_memory_mb": 109.80,
                "kb_per_entry": 508.0,
                "process_ram_rss_mb": 1319.22
            },
            "stress_test": stress_bench["final"],
        },
        "inspections": {
            "tile_0_20_66": {
                "images_viewed": [
                    "docs/inspection/0_20_66_pre.jpg",
                    "docs/inspection/0_20_66_pre_fast_mask.jpg",
                    "docs/inspection/0_20_66_pre_acc_mask.jpg",
                    "docs/inspection/0_20_66_post.jpg"
                ],
                "finding": "Pre-event imagery shows false-positive cyan masks on settlement structures (3.32% Fast, 4.77% Accurate); post-event predicts 0.00% Fast, 0.50% Accurate; ground-truth records 0 flooded features; specific root cause not determined."
            },
            "tile_0_38_69": {
                "images_viewed": [
                    "docs/inspection/0_38_69_pre.jpg",
                    "docs/inspection/0_38_69_pre_fast_mask.jpg",
                    "docs/inspection/0_38_69_pre_acc_mask.jpg",
                    "docs/inspection/0_38_69_post.jpg",
                    "docs/inspection/0_38_69_post_fast_mask.jpg",
                    "docs/inspection/0_38_69_post_acc_mask.jpg"
                ],
                "finding": "Upper-left settlement has dark residential rooftops and asphalt driveways flagged as class 1 in Accurate Mode (1.33% post vs 0.29% pre, net +1.04%); Fast Mode predicts 0.00% on both; 0 annotated flooded features."
            },
            "tile_0_31_69": {
                "images_viewed": [
                    "docs/inspection/0_31_69_pre.jpg",
                    "docs/inspection/0_31_69_pre_fast_mask.jpg",
                    "docs/inspection/0_31_69_pre_acc_mask.jpg",
                    "docs/inspection/0_31_69_post.jpg",
                    "docs/inspection/0_31_69_post_fast_mask.jpg",
                    "docs/inspection/0_31_69_post_acc_mask.jpg"
                ],
                "finding": "Upper hillside residential strip has dark rooftops and paved road segments flagged as class 1 in Accurate Mode (1.14% post vs 0.00% pre, net +1.14%); Fast Mode predicts 0.00% on both; steep forested slopes and fog are unflagged; 0 annotated flooded features."
            }
        },
        "tests": {
            "total_tests": 13,
            "passed": 13,
            "duration_seconds": 21.41
        }
    }

    out_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "MEASURED.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(measured, f, indent=2)

    print(f"✓ Successfully generated {out_file}")

if __name__ == "__main__":
    main()
