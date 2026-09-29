import numpy as np

try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

class TNFCLCrossAttentionFusion:
    def __init__(self, embed_dim=16):
        self.embed_dim = embed_dim
        if TORCH_AVAILABLE:
            self.net_encoder = nn.Linear(4, embed_dim) # [port, asn_code, country_code, is_flagged]
            self.chain_encoder = nn.Linear(4, embed_dim) # [sent, rec, tx_count, avg_amount]
            self.cross_attn = nn.MultiheadAttention(embed_dim=embed_dim, num_heads=2, batch_first=True)
            self.classifier = nn.Sequential(
                nn.Linear(embed_dim, 8),
                nn.ReLU(),
                nn.Linear(8, 1),
                nn.Sigmoid()
            )
        
    def fuse_features_numpy(self, net_feats, chain_feats):
        # Fallback NumPy cross-attention: Q=net, K=V=chain
        # net_feats: [B, 4], chain_feats: [B, 4]
        d = net_feats.shape[-1]
        scores = np.dot(net_feats, chain_feats.T) / np.sqrt(d)
        scores_shift = scores - np.max(scores, axis=-1, keepdims=True)
        exp_scores = np.exp(scores_shift)
        weights = exp_scores / (np.sum(exp_scores, axis=-1, keepdims=True) + 1e-9)
        fused = np.dot(weights, chain_feats)
        combined = 0.5 * net_feats + 0.5 * fused
        fusion_score = np.mean(combined, axis=-1)
        return fusion_score

    def predict_fusion_risk(self, net_feats, chain_feats):
        # net_feats: list/arr of 4 floats, chain_feats: list/arr of 4 floats
        net_arr = np.array(net_feats, dtype=np.float32)
        chain_arr = np.array(chain_feats, dtype=np.float32)
        
        if len(net_arr.shape) == 1:
            net_arr = np.expand_dims(net_arr, axis=0)
            chain_arr = np.expand_dims(chain_arr, axis=0)
            
        if TORCH_AVAILABLE:
            with torch.no_grad():
                net_t = torch.tensor(net_arr)
                chain_t = torch.tensor(chain_arr)
                
                net_e = self.net_encoder(net_t).unsqueeze(1) # [B, 1, E]
                chain_e = self.chain_encoder(chain_t).unsqueeze(1) # [B, 1, E]
                
                attn_out, _ = self.cross_attn(net_e, chain_e, chain_e)
                risk_prob = self.classifier(attn_out.squeeze(1))
                return risk_prob.numpy().flatten()
        else:
            return self.fuse_features_numpy(net_arr, chain_arr)

if __name__ == "__main__":
    fusion_model = TNFCLCrossAttentionFusion()
    sample_net = [8333, 1001, 1, 1]
    sample_chain = [10.5, 2.0, 5, 2.1]
    score = fusion_model.predict_fusion_risk(sample_net, sample_chain)
    print(f"TNF-CL Cross-Attention Fusion Risk Score Output: {score}")
