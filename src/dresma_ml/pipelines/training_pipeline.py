"""End-to-end Kubeflow pipeline for Dresma XGBoost learning-to-rank training."""

from kfp import dsl

from dresma_ml.pipelines.components.build_dataset import materialize_training_dataset
from dresma_ml.pipelines.components.evaluate import evaluate_xgboost_ranker
from dresma_ml.pipelines.components.register import register_model
from dresma_ml.pipelines.components.train import train_xgboost_ranker
from dresma_ml.pipelines.components.validate import validate_xgboost_ranker


@dsl.pipeline(
    name="dresma-xgboost-training",
    description="End-to-end LTR training pipeline",
)
def training_pipeline(
    project_id: str,
    dataset_id: str,
    run_id: str,
    bucket_name: str,
    spanner_instance: str,
    spanner_database: str,
) -> None:
    build_dataset_op = materialize_training_dataset(
        project_id=project_id,
        dataset_id=dataset_id,
        run_id=run_id,
        spanner_instance=spanner_instance,
        spanner_database=spanner_database,
    )

    train_op = train_xgboost_ranker(
        project_id=project_id,
        dataset_id=dataset_id,
        train_table=build_dataset_op.output,
    )

    eval_op = evaluate_xgboost_ranker(
        model_artifact=train_op.outputs["model_artifact"],
        test_data_artifact=train_op.outputs["test_data_artifact"],
    )

    validate_op = validate_xgboost_ranker(
        model_artifact=train_op.outputs["model_artifact"],
        metrics=eval_op.outputs["metrics"],
    )

    register_op = register_model(
        model_artifact=train_op.outputs["model_artifact"],
        project_id=project_id,
        run_id=run_id,
        bucket_name=bucket_name,
        spanner_instance=spanner_instance,
        spanner_database=spanner_database,
    )
    register_op.after(validate_op)
