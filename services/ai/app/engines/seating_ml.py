"""ML-based seating preference engine using scikit-learn."""

from __future__ import annotations

import logging
import os
import pickle
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger(__name__)

MODEL_DIR = Path(os.getenv("AI_MODEL_DIR", "/tmp/gastropilot_models"))
MIN_TRAINING_SAMPLES = 20


class SeatingMLEngine:
    """
    Learns guest seating preferences from historical data.

    Uses a RandomForestClassifier to predict which table a guest
    would prefer, based on features like visit frequency, party size,
    time of day, day of week, and area preferences.

    Falls back to rule-based scoring when insufficient training data.
    """

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.model: RandomForestClassifier | None = None
        self.table_encoder = LabelEncoder()
        self.guest_encoder = LabelEncoder()
        self.area_encoder = LabelEncoder()
        self._guest_stats: dict[str, dict[str, Any]] = {}
        self._feedback_buffer: list[dict[str, Any]] = []
        self._is_trained = False
        self._model_accuracy: float | None = None

        self._try_load()

    # ── Persistence ───────────────────────────────────────────────────────
    # NOTE: pickle is used intentionally for scikit-learn model serialization
    # as required by the project spec. The model files are generated locally
    # and never loaded from untrusted sources.

    def _model_path(self) -> Path:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        return MODEL_DIR / f"seating_ml_{self.tenant_id}.pkl"

    def _try_load(self) -> None:
        path = self._model_path()
        if path.exists():
            try:
                with open(path, "rb") as f:
                    state = pickle.load(f)  # noqa: S301
                self.model = state["model"]
                self.table_encoder = state["table_encoder"]
                self.guest_encoder = state["guest_encoder"]
                self.area_encoder = state["area_encoder"]
                self._guest_stats = state["guest_stats"]
                self._feedback_buffer = state.get("feedback_buffer", [])
                self._is_trained = True
                self._model_accuracy = state.get("model_accuracy")
                logger.info(
                    "Loaded ML model for tenant %s (%d guest profiles)",
                    self.tenant_id,
                    len(self._guest_stats),
                )
            except Exception:
                logger.warning(
                    "Failed to load ML model for tenant %s, starting fresh",
                    self.tenant_id,
                    exc_info=True,
                )

    def _save(self) -> None:
        path = self._model_path()
        state = {
            "model": self.model,
            "table_encoder": self.table_encoder,
            "guest_encoder": self.guest_encoder,
            "area_encoder": self.area_encoder,
            "guest_stats": self._guest_stats,
            "feedback_buffer": self._feedback_buffer,
            "model_accuracy": self._model_accuracy,
        }
        with open(path, "wb") as f:
            pickle.dump(state, f)
        logger.info("Saved ML model for tenant %s", self.tenant_id)

    # ── Training ──────────────────────────────────────────────────────────

    def train(self, history_data: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Train the model from historical seating data.

        Each entry should have: guest_id, table_id, party_size, day_of_week,
        hour, area (optional), satisfaction (optional), duration_minutes,
        revenue (optional).

        Returns training summary dict.
        """
        if len(history_data) < MIN_TRAINING_SAMPLES:
            self._build_guest_stats(history_data)
            self._save()
            return {
                "records_used": len(history_data),
                "model_accuracy": None,
                "message": (
                    f"Insufficient data for ML training "
                    f"(need {MIN_TRAINING_SAMPLES}, got {len(history_data)}). "
                    f"Guest stats built for rule-based fallback."
                ),
            }

        # Build guest statistics (used for both ML and fallback)
        self._build_guest_stats(history_data)

        # Prepare features
        all_guest_ids = list({e["guest_id"] for e in history_data})
        all_table_ids = list({e["table_id"] for e in history_data})
        all_areas = list({e.get("area", "unknown") or "unknown" for e in history_data})

        self.guest_encoder.fit(all_guest_ids)
        self.table_encoder.fit(all_table_ids)
        self.area_encoder.fit(all_areas)

        # Build feature matrix
        # Guest visit frequency per table
        guest_table_freq: dict[str, Counter] = defaultdict(Counter)
        for entry in history_data:
            guest_table_freq[entry["guest_id"]][entry["table_id"]] += 1

        X = []
        y = []
        for entry in history_data:
            gid = entry["guest_id"]
            tid = entry["table_id"]
            area = entry.get("area", "unknown") or "unknown"

            guest_enc = self.guest_encoder.transform([gid])[0]
            area_enc = self.area_encoder.transform([area])[0]
            freq = guest_table_freq[gid][tid]
            total_visits = sum(guest_table_freq[gid].values())
            freq_ratio = freq / total_visits if total_visits > 0 else 0.0

            features = [
                guest_enc,
                entry.get("party_size", 2),
                entry.get("hour", 12),
                entry.get("day_of_week", 0),
                area_enc,
                freq_ratio,
                freq,
                entry.get("satisfaction", 3.0) or 3.0,
                entry.get("duration_minutes", 60) or 60,
            ]
            X.append(features)
            y.append(self.table_encoder.transform([tid])[0])

        X_arr = np.array(X, dtype=np.float64)
        y_arr = np.array(y)

        # Train RandomForest
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1,
        )

        # Cross-validation for accuracy estimate
        if len(history_data) >= 50:
            cv_folds = min(5, len(set(y_arr)))
            if cv_folds >= 2:
                scores = cross_val_score(self.model, X_arr, y_arr, cv=cv_folds)
                self._model_accuracy = round(float(np.mean(scores)), 4)

        self.model.fit(X_arr, y_arr)
        self._is_trained = True
        self._save()

        logger.info(
            "Trained ML model for tenant %s: %d records, accuracy=%.4f",
            self.tenant_id,
            len(history_data),
            self._model_accuracy or 0.0,
        )

        return {
            "records_used": len(history_data),
            "model_accuracy": self._model_accuracy,
            "message": "Model trained successfully.",
        }

    def _build_guest_stats(self, history_data: list[dict[str, Any]]) -> None:
        """Build per-guest statistics from history."""
        stats: dict[str, dict[str, Any]] = {}

        guest_records: dict[str, list[dict]] = defaultdict(list)
        for entry in history_data:
            guest_records[entry["guest_id"]].append(entry)

        for gid, records in guest_records.items():
            table_counts: Counter = Counter()
            area_counts: Counter = Counter()
            party_sizes: list[int] = []
            satisfactions: list[float] = []

            for r in records:
                table_counts[r["table_id"]] += 1
                area = r.get("area")
                if area:
                    area_counts[area] += 1
                party_sizes.append(r.get("party_size", 2))
                sat = r.get("satisfaction")
                if sat is not None:
                    satisfactions.append(sat)

            stats[gid] = {
                "table_counts": dict(table_counts),
                "area_counts": dict(area_counts),
                "avg_party_size": sum(party_sizes) / len(party_sizes),
                "avg_satisfaction": (
                    sum(satisfactions) / len(satisfactions) if satisfactions else None
                ),
                "total_visits": len(records),
            }

        self._guest_stats = stats

    # ── Prediction ────────────────────────────────────────────────────────

    def predict_preference(
        self,
        guest_id: str,
        available_tables: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Predict preference scores for available tables.

        Returns list of {table_id, ml_score, source} sorted by score desc.
        Falls back to rule-based scoring if model is not trained or
        guest is unknown.
        """
        context = context or {}
        party_size = context.get("party_size", 2)
        hour = context.get("hour", 12)
        day_of_week = context.get("day_of_week", 0)

        # Fallback: rule-based from guest stats
        if not self._is_trained or self.model is None:
            return self._rule_based_preferences(guest_id, available_tables, party_size)

        # Check if guest is known to the model
        if guest_id not in self.guest_encoder.classes_:
            return self._rule_based_preferences(guest_id, available_tables, party_size)

        guest_enc = self.guest_encoder.transform([guest_id])[0]
        guest_stats = self._guest_stats.get(guest_id, {})
        table_counts = guest_stats.get("table_counts", {})
        total_visits = guest_stats.get("total_visits", 1)

        results = []
        for table in available_tables:
            tid = table["table_id"]
            area = table.get("area", "unknown") or "unknown"

            # Encode area (use 0 for unknown areas)
            if area in self.area_encoder.classes_:
                area_enc = self.area_encoder.transform([area])[0]
            else:
                area_enc = 0

            freq = table_counts.get(tid, 0)
            freq_ratio = freq / total_visits if total_visits > 0 else 0.0
            avg_sat = guest_stats.get("avg_satisfaction", 3.0) or 3.0

            features = np.array(
                [
                    [
                        guest_enc,
                        party_size,
                        hour,
                        day_of_week,
                        area_enc,
                        freq_ratio,
                        freq,
                        avg_sat,
                        60,  # default duration for prediction
                    ]
                ],
                dtype=np.float64,
            )

            # Get probability distribution across tables
            if tid in self.table_encoder.classes_:
                table_idx = list(self.table_encoder.classes_).index(tid)
                proba = self.model.predict_proba(features)[0]
                if table_idx < len(proba):
                    ml_score = float(proba[table_idx]) * 100
                else:
                    ml_score = 0.0
            else:
                # Unknown table — give neutral score
                ml_score = 10.0

            results.append(
                {
                    "table_id": tid,
                    "ml_score": round(ml_score, 2),
                    "source": "ml",
                }
            )

        results.sort(key=lambda x: x["ml_score"], reverse=True)
        return results

    def _rule_based_preferences(
        self,
        guest_id: str,
        available_tables: list[dict[str, Any]],
        party_size: int,
    ) -> list[dict[str, Any]]:
        """Fallback scoring based on guest visit statistics."""
        stats = self._guest_stats.get(guest_id)

        results = []
        for table in available_tables:
            tid = table["table_id"]
            score = 50.0  # neutral baseline

            if stats:
                table_counts = stats.get("table_counts", {})
                total_visits = stats.get("total_visits", 1)
                freq = table_counts.get(tid, 0)

                # Frequency bonus: up to 30 points
                if total_visits > 0:
                    score += (freq / total_visits) * 30

                # Area preference bonus: up to 10 points
                area_counts = stats.get("area_counts", {})
                table_area = table.get("area")
                if table_area and area_counts:
                    total_area_visits = sum(area_counts.values())
                    if total_area_visits > 0:
                        area_pref = area_counts.get(table_area, 0) / total_area_visits
                        score += area_pref * 10

            results.append(
                {
                    "table_id": tid,
                    "ml_score": round(score, 2),
                    "source": "rule_based",
                }
            )

        results.sort(key=lambda x: x["ml_score"], reverse=True)
        return results

    # ── Feedback ──────────────────────────────────────────────────────────

    def record_feedback(self, feedback: dict[str, Any]) -> int:
        """
        Record seating feedback for future training.

        Returns total buffered feedback count.
        """
        self._feedback_buffer.append(feedback)
        self._save()
        return len(self._feedback_buffer)

    # ── Guest Preference Summary ──────────────────────────────────────────

    def get_guest_preference(self, guest_id: str) -> dict[str, Any] | None:
        """Return learned preference summary for a guest."""
        stats = self._guest_stats.get(guest_id)
        if not stats:
            return None

        table_counts = stats.get("table_counts", {})
        sorted_tables = sorted(table_counts.items(), key=lambda x: x[1], reverse=True)

        area_counts = stats.get("area_counts", {})
        sorted_areas = sorted(area_counts.items(), key=lambda x: x[1], reverse=True)

        return {
            "guest_id": guest_id,
            "preferred_tables": [
                {"table_id": tid, "score": float(cnt), "visit_count": cnt}
                for tid, cnt in sorted_tables
            ],
            "preferred_areas": [area for area, _ in sorted_areas],
            "avg_party_size": stats.get("avg_party_size", 0),
            "avg_satisfaction": stats.get("avg_satisfaction"),
            "total_visits": stats.get("total_visits", 0),
            "data_source": "ml" if self._is_trained else "rule_based",
        }

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    @property
    def model_accuracy(self) -> float | None:
        return self._model_accuracy

    @property
    def feedback_count(self) -> int:
        return len(self._feedback_buffer)


# ── Module-level engine cache ─────────────────────────────────────────────────

_engines: dict[str, SeatingMLEngine] = {}


def get_engine(tenant_id: str) -> SeatingMLEngine:
    """Get or create a SeatingMLEngine for a tenant."""
    if tenant_id not in _engines:
        _engines[tenant_id] = SeatingMLEngine(tenant_id)
    return _engines[tenant_id]
