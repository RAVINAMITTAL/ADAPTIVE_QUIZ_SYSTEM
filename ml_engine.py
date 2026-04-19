import os
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import joblib

from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import train_test_split

# Difficulty levels
DIFFICULTY_LEVELS = ["Easy", "Medium", "Hard"]
DIFFICULTY_MAP = {"Easy": 0, "Medium": 1, "Hard": 2}
REVERSE_DIFFICULTY_MAP = {0: "Easy", 1: "Medium", 2: "Hard"}

# Model paths
MODEL_DIR = os.path.join(os.path.dirname(__file__), "ml_models")
LOGISTIC_MODEL_PATH = os.path.join(MODEL_DIR, "logistic_model.joblib")
TREE_MODEL_PATH = os.path.join(MODEL_DIR, "decision_tree_model.joblib")
SCALER_PATH = os.path.join(MODEL_DIR, "scaler.joblib")


# ============ BASIC RULE ENGINE ============
def basic_rule_engine(accuracy: float, avg_time_sec: float, prev_difficulty: str) -> str:
    """
    Simple rule-based difficulty adjustment.
    - High accuracy + fast time → increase difficulty
    - Low accuracy or slow time → decrease difficulty
    """
    diff_idx = DIFFICULTY_MAP.get(prev_difficulty, 1)
    
    # Fast and accurate → harder
    if accuracy >= 0.8 and avg_time_sec < 30:
        return REVERSE_DIFFICULTY_MAP.get(min(diff_idx + 1, 2), "Hard")
    
    # Good accuracy → stay or increase
    elif accuracy >= 0.7:
        return REVERSE_DIFFICULTY_MAP.get(min(diff_idx + 1, 2), "Medium")
    
    # Moderate accuracy → stay same
    elif accuracy >= 0.5:
        return prev_difficulty
    
    # Low accuracy → decrease
    else:
        return REVERSE_DIFFICULTY_MAP.get(max(diff_idx - 1, 0), "Easy")


# ============ FEATURE ENGINEERING ============
def extract_features(stats: Dict) -> np.ndarray:
    """
    Extract ML features from user performance stats.
    
    Features:
    1. accuracy (0-1)
    2. avg_time_per_question (seconds)
    3. previous_difficulty_encoded (0, 1, 2)
    4. total_attempts_on_topic
    5. recent_trend (accuracy change over last 3 attempts)
    6. time_consistency (std dev of time)
    """
    accuracy = stats.get("accuracy", 0.5)
    avg_time = stats.get("avg_time_sec", 60)
    prev_diff = DIFFICULTY_MAP.get(stats.get("prev_difficulty", "Medium"), 1)
    total_attempts = stats.get("total_attempts", 1)
    recent_trend = stats.get("recent_trend", 0.0)
    time_consistency = stats.get("time_consistency", 10.0)
    
    # Normalize avg_time (cap at 120 seconds)
    avg_time_normalized = min(avg_time / 120.0, 1.0)
    
    # Normalize total_attempts (log scale)
    attempts_normalized = np.log1p(total_attempts) / 5.0
    
    features = np.array([
        accuracy,
        avg_time_normalized,
        prev_diff / 2.0,  # normalize to 0-1
        attempts_normalized,
        recent_trend,
        min(time_consistency / 30.0, 1.0)
    ])
    
    return features.reshape(1, -1)


# ============ LOGISTIC REGRESSION MODEL ============
class LogisticDifficultyModel:
    """
    Logistic Regression model for difficulty prediction.
    Predicts probability of success at each difficulty level.
    """
    
    def __init__(self):
        # FIXED: Removed multi_class parameter (deprecated in scikit-learn 1.3+)
        self.model = LogisticRegression(
            solver='lbfgs',
            max_iter=1000,
            random_state=42
        )
        self.scaler = StandardScaler()
        self.is_fitted = False
    
    def fit(self, X: np.ndarray, y: np.ndarray):
        """Train the model on historical data."""
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)
        self.is_fitted = True
    
    def predict(self, features: np.ndarray) -> Tuple[str, Dict]:
        """
        Predict next difficulty level.
        Returns (difficulty, confidence_scores)
        """
        if not self.is_fitted:
            return "Medium", {"Easy": 0.33, "Medium": 0.34, "Hard": 0.33}
        
        X_scaled = self.scaler.transform(features)
        proba = self.model.predict_proba(X_scaled)[0]
        
        # Get difficulty with highest probability
        pred_idx = np.argmax(proba)
        
        confidence = {
            "Easy": float(proba[0]) if len(proba) > 0 else 0.33,
            "Medium": float(proba[1]) if len(proba) > 1 else 0.34,
            "Hard": float(proba[2]) if len(proba) > 2 else 0.33
        }
        
        return REVERSE_DIFFICULTY_MAP.get(pred_idx, "Medium"), confidence
    
    def save(self, model_path: str = LOGISTIC_MODEL_PATH, scaler_path: str = SCALER_PATH):
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        joblib.dump(self.model, model_path)
        joblib.dump(self.scaler, scaler_path)
    
    def load(self, model_path: str = LOGISTIC_MODEL_PATH, scaler_path: str = SCALER_PATH):
        if os.path.exists(model_path) and os.path.exists(scaler_path):
            self.model = joblib.load(model_path)
            self.scaler = joblib.load(scaler_path)
            self.is_fitted = True
            return True
        return False


# ============ DECISION TREE MODEL ============
class DecisionTreeDifficultyModel:
    """
    Decision Tree model for difficulty prediction.
    More interpretable, good for understanding decision rules.
    """
    
    def __init__(self):
        self.model = DecisionTreeClassifier(
            max_depth=5,
            min_samples_split=10,
            min_samples_leaf=5,
            random_state=42
        )
        self.is_fitted = False
    
    def fit(self, X: np.ndarray, y: np.ndarray):
        """Train the model."""
        self.model.fit(X, y)
        self.is_fitted = True
    
    def predict(self, features: np.ndarray) -> Tuple[str, Dict]:
        """Predict next difficulty."""
        if not self.is_fitted:
            return "Medium", {"Easy": 0.33, "Medium": 0.34, "Hard": 0.33}
        
        proba = self.model.predict_proba(features)[0]
        pred_idx = np.argmax(proba)
        
        confidence = {
            "Easy": float(proba[0]) if len(proba) > 0 else 0.33,
            "Medium": float(proba[1]) if len(proba) > 1 else 0.34,
            "Hard": float(proba[2]) if len(proba) > 2 else 0.33
        }
        
        return REVERSE_DIFFICULTY_MAP.get(pred_idx, "Medium"), confidence
    
    def save(self, path: str = TREE_MODEL_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump(self.model, path)
    
    def load(self, path: str = TREE_MODEL_PATH):
        if os.path.exists(path):
            self.model = joblib.load(path)
            self.is_fitted = True
            return True
        return False


# ============ SYNTHETIC DATA GENERATOR ============
def generate_training_data(n_samples: int = 1000) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generate synthetic training data based on realistic patterns.
    Used to bootstrap the ML models before real user data is available.
    """
    np.random.seed(42)
    
    X = []
    y = []
    
    for _ in range(n_samples):
        # Random baseline stats
        accuracy = np.random.beta(5, 3)  # skewed towards higher accuracy
        avg_time = np.random.gamma(3, 15)  # centered around 45 sec
        prev_diff = np.random.choice([0, 1, 2], p=[0.25, 0.5, 0.25])
        total_attempts = np.random.poisson(5) + 1
        recent_trend = np.random.normal(0, 0.1)
        time_consistency = np.random.exponential(10)
        
        # Normalize features
        features = [
            accuracy,
            min(avg_time / 120.0, 1.0),
            prev_diff / 2.0,
            np.log1p(total_attempts) / 5.0,
            recent_trend,
            min(time_consistency / 30.0, 1.0)
        ]
        
        # Determine target difficulty based on realistic rules
        if accuracy > 0.8 and avg_time < 45:
            target = min(prev_diff + 1, 2)
        elif accuracy > 0.6:
            target = prev_diff
        elif accuracy > 0.4:
            target = max(prev_diff - 1, 0) if avg_time > 60 else prev_diff
        else:
            target = max(prev_diff - 1, 0)
        
        # Add some noise
        if np.random.random() < 0.1:
            target = np.random.choice([0, 1, 2])
        
        X.append(features)
        y.append(target)
    
    return np.array(X), np.array(y)


# ============ MODEL INITIALIZATION ============
_logistic_model = None
_tree_model = None


def get_models() -> Tuple[LogisticDifficultyModel, DecisionTreeDifficultyModel]:
    """Get or initialize ML models."""
    global _logistic_model, _tree_model
    
    if _logistic_model is None:
        _logistic_model = LogisticDifficultyModel()
        if not _logistic_model.load():
            # Train on synthetic data
            X, y = generate_training_data(1000)
            _logistic_model.fit(X, y)
            _logistic_model.save()
    
    if _tree_model is None:
        _tree_model = DecisionTreeDifficultyModel()
        if not _tree_model.load():
            X, y = generate_training_data(1000)
            _tree_model.fit(X, y)
            _tree_model.save()
    
    return _logistic_model, _tree_model


# ============ WEAK TOPIC DETECTION ============
def detect_weak_topics(user_attempts: List[Dict]) -> List[str]:
    """
    Analyze user's quiz history to identify weak topics.
    Returns list of topics where accuracy < 60%.
    """
    topic_stats = {}
    
    for attempt in user_attempts:
        topic = attempt.get("topic", "Unknown")
        score = attempt.get("score", 0)
        total = attempt.get("total", 1)
        
        if topic not in topic_stats:
            topic_stats[topic] = {"correct": 0, "total": 0}
        
        topic_stats[topic]["correct"] += score
        topic_stats[topic]["total"] += total
    
    weak_topics = []
    for topic, stats in topic_stats.items():
        if stats["total"] > 0:
            accuracy = stats["correct"] / stats["total"]
            if accuracy < 0.6:
                weak_topics.append(topic)
    
    return weak_topics


# ============ MAIN ADAPTIVE ENGINE ============
def get_next_difficulty(
    stats: Dict,
    model_type: str = "logistic"
) -> Dict:
    """
    Determine next quiz difficulty using ML models.
    
    Args:
        stats: {
            "accuracy": 0.7,
            "avg_time_sec": 45,
            "prev_difficulty": "Medium",
            "total_attempts": 5,
            "recent_trend": 0.05,
            "time_consistency": 8.0,
            "user_attempts": [...]  # for weak topic detection
        }
        model_type: "logistic", "tree", or "rule"
    
    Returns:
        {
            "next_difficulty": "Hard",
            "confidence": {"Easy": 0.1, "Medium": 0.3, "Hard": 0.6},
            "weak_topics": ["Topic A", "Topic B"],
            "model_used": "logistic"
        }
    """
    # Extract features
    features = extract_features(stats)
    
    # Get prediction
    if model_type == "rule":
        next_diff = basic_rule_engine(
            stats.get("accuracy", 0.5),
            stats.get("avg_time_sec", 60),
            stats.get("prev_difficulty", "Medium")
        )
        confidence = {next_diff: 1.0}
        for d in DIFFICULTY_LEVELS:
            if d not in confidence:
                confidence[d] = 0.0
    else:
        logistic_model, tree_model = get_models()
        
        if model_type == "tree":
            next_diff, confidence = tree_model.predict(features)
        else:
            next_diff, confidence = logistic_model.predict(features)
    
    # Detect weak topics
    user_attempts = stats.get("user_attempts", [])
    weak_topics = detect_weak_topics(user_attempts)
    
    return {
        "next_difficulty": next_diff,
        "confidence": confidence,
        "weak_topics": weak_topics,
        "model_used": model_type
    }


# ============ MODEL RETRAINING ============
def retrain_models_with_user_data(quiz_attempts: List[Dict]):
    """
    Retrain ML models with real user data.
    Call this periodically or when enough new data is collected.
    """
    if len(quiz_attempts) < 100:
        return False
    
    X = []
    y = []
    
    for i, attempt in enumerate(quiz_attempts[:-1]):
        next_attempt = quiz_attempts[i + 1]
        
        # Current attempt features
        accuracy = attempt["score"] / attempt["total"] if attempt["total"] > 0 else 0.5
        avg_time = attempt.get("time_taken_sec", 60) / attempt["total"] if attempt["total"] > 0 else 30
        prev_diff = DIFFICULTY_MAP.get(attempt["difficulty"], 1)
        
        features = [
            accuracy,
            min(avg_time / 120.0, 1.0),
            prev_diff / 2.0,
            0.5,  # placeholder for total_attempts
            0.0,  # placeholder for trend
            0.3   # placeholder for consistency
        ]
        
        # Target is the next attempt's difficulty
        target = DIFFICULTY_MAP.get(next_attempt["difficulty"], 1)
        
        X.append(features)
        y.append(target)
    
    X = np.array(X)
    y = np.array(y)
    
    # Retrain models
    logistic_model, tree_model = get_models()
    logistic_model.fit(X, y)
    logistic_model.save()
    tree_model.fit(X, y)
    tree_model.save()
    
    return True
