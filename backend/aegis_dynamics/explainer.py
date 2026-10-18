"""
AegisDynamics - SHAP Explainability & Root-Cause Attribution Layer
Explains the Self-Supervised World Model by computing Shapley feature attributions
on the forecast reconstruction residual error e(t+1).
"""

import shap
import torch
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Tuple, Optional
from parser import FEATURE_NAMES, STAGE_NAMES

class TemporalStateExplainer:
    """
    SHAP-based Explainer for Self-Supervised World Model.
    Computes local and global feature attribution on the prediction residual error e(t+1).
    """
    def __init__(self, model: torch.nn.Module, background_data: np.ndarray):
        """
        background_data: numpy array of shape [num_samples, seq_len, num_features]
        """
        self.model = model
        self.model.eval()
        self.background_data = background_data
        self.seq_len = background_data.shape[1]
        self.num_features = background_data.shape[2]
        
        # Flatten background for kernel explanation
        self.bg_flat = background_data.reshape(background_data.shape[0], -1)
        
        # Define prediction wrapper evaluating the forecast residual deviation
        def model_residual_flat(flat_x: np.ndarray) -> np.ndarray:
            batch_size = flat_x.shape[0]
            reshaped_x = flat_x.reshape(batch_size, self.seq_len, self.num_features)
            with torch.no_grad():
                tensor_x = torch.tensor(reshaped_x, dtype=torch.float32)
                pred_state, _ = self.model(tensor_x)
                # Compute deviation from benign baseline mean
                mean_t = self.model.benign_mean.unsqueeze(0).to(pred_state.device)
                residuals = self.model.compute_residual_error(pred_state, mean_t)
                return residuals.cpu().numpy().flatten()
                
        self.predict_fn = model_residual_flat

        # Initialize SHAP KernelExplainer directly on empirical background samples
        bg_sample = self.bg_flat[:min(8, len(self.bg_flat))]
        self.explainer = shap.KernelExplainer(self.predict_fn, bg_sample)
        
    def explain_instance(
        self, 
        sample_seq: np.ndarray, 
        top_k: int = 3
    ) -> Dict[str, Any]:
        """
        Computes SHAP attributions for a single sequence [seq_len, num_features]
        and returns the top_k driving features behind the forecasted state deviation.
        """
        if len(sample_seq.shape) == 2:
            flat_sample = sample_seq.reshape(1, -1)
        else:
            flat_sample = sample_seq.reshape(sample_seq.shape[0], -1)
            
        shap_values = self.explainer.shap_values(flat_sample, nsamples=80, silent=True)
        if isinstance(shap_values, list):
            shap_arr = shap_values[0]
        else:
            shap_arr = shap_values
            
        # Reshape attributions back to [seq_len, num_features]
        shap_matrix = shap_arr[0].reshape(self.seq_len, self.num_features)
        
        # Aggregate across sequence lookback (mean signed & magnitude)
        feature_signed_imp = np.mean(shap_matrix, axis=0)
        feature_abs_imp = np.mean(np.abs(shap_matrix), axis=0)
        
        latest_values = sample_seq[-1, :] if len(sample_seq.shape) == 2 else sample_seq[0, -1, :]
        
        # Rank by absolute importance
        ranked_indices = np.argsort(-feature_abs_imp)
        
        top_features = []
        for rank in range(min(top_k, len(FEATURE_NAMES))):
            idx = ranked_indices[rank]
            direction = float(feature_signed_imp[idx])
            top_features.append({
                "rank": rank + 1,
                "feature": FEATURE_NAMES[idx],
                "shap_importance": float(feature_abs_imp[idx]),
                "shap_direction": direction,
                "current_value": float(latest_values[idx]),
                "impact": "Increases Attack Risk (Anomaly)" if direction > 0 else "Stabilizes Benign Baseline"
            })
            
        all_features_df = pd.DataFrame({
            "Feature": FEATURE_NAMES,
            "Importance": feature_abs_imp,
            "Directional_SHAP": feature_signed_imp,
            "Latest_Value": latest_values
        }).sort_values(by="Importance", ascending=False).reset_index(drop=True)
        
        top_names = [f["feature"] for f in top_features]
        summary_text = (
            f"Top state transition drivers: {top_names[0]} (SHAP {top_features[0]['shap_direction']:+.3f}), "
            f"{top_names[1]} (SHAP {top_features[1]['shap_direction']:+.3f}), and "
            f"{top_names[2]} (SHAP {top_features[2]['shap_direction']:+.3f})."
        )
        
        return {
            "top_features": top_features,
            "all_features_df": all_features_df,
            "temporal_shap_matrix": shap_matrix,
            "summary_text": summary_text
        }

if __name__ == "__main__":
    print("[*] Testing explainer.py on Self-Supervised World Model...")
    from model import SelfSupervisedWorldModel
    
    bg = np.random.randn(15, 5, 14).astype(np.float32)
    test_s = np.random.randn(5, 14).astype(np.float32)
    
    m = SelfSupervisedWorldModel(input_dim=14)
    expl = TemporalStateExplainer(m, bg)
    res = expl.explain_instance(test_s, top_k=3)
    print("[+] Top 3 Drivers:")
    for f in res["top_features"]:
        print(f"   #{f['rank']}: {f['feature']} (Score: {f['shap_direction']:+.4f}) -> {f['impact']}")
