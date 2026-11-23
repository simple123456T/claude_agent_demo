from app.semantic.registry import (
    Aggregation,
    ColumnDefinition,
    DatasetDefinition,
    MetricDefinition,
)

DEMO_SCHEMA = "datagent_demo"
DEMO_TABLE = "demo_sales"


def build_demo_dataset(schema: str = DEMO_SCHEMA) -> DatasetDefinition:
    columns = {
        name: ColumnDefinition(name=name)
        for name in [
            "order_id",
            "order_month",
            "region",
            "product",
            "category",
            "customer_id",
            "amount",
            "quantity",
        ]
    }
    return DatasetDefinition(
        name="sales",
        version="2026.11.1",
        schema_name=schema,
        table=DEMO_TABLE,
        label="销售订单",
        description="演示用销售订单明细：每行一个订单，覆盖区域、产品、品类和月份。金额为含税销售额，单位元。",
        columns=columns,
        dimensions={
            "region": "region",
            "product": "product",
            "category": "category",
            "month": "order_month",
        },
        dimension_labels={
            "region": "区域",
            "product": "产品",
            "category": "品类",
            "month": "月份",
        },
        time_dimensions=frozenset({"month"}),
        metrics={
            "revenue": MetricDefinition(
                name="revenue",
                aggregation=Aggregation.SUM,
                column="amount",
                label="销售额",
                unit="元",
                description="订单含税金额合计",
            ),
            "orders": MetricDefinition(
                name="orders",
                aggregation=Aggregation.COUNT,
                label="订单数",
                unit="单",
                description="订单行数",
            ),
            "customers": MetricDefinition(
                name="customers",
                aggregation=Aggregation.COUNT_DISTINCT,
                column="customer_id",
                label="客户数",
                unit="个",
                description="去重后的下单客户数",
            ),
            "quantity": MetricDefinition(
                name="quantity",
                aggregation=Aggregation.SUM,
                column="quantity",
                label="销量",
                unit="件",
                description="售出件数合计",
            ),
            "avg_order_value": MetricDefinition(
                name="avg_order_value",
                aggregation=Aggregation.AVG,
                column="amount",
                label="客单价",
                unit="元",
                description="平均每单金额",
            ),
        },
        synonyms={
            "revenue": ["营收", "销售收入", "收入", "销售金额", "GMV"],
            "orders": ["订单量", "单量"],
            "customers": ["客户量", "下单客户"],
            "quantity": ["销售数量", "出货量"],
            "avg_order_value": ["平均订单金额", "单均金额"],
            "region": ["地区", "大区", "区域"],
            "product": ["商品", "产品名称"],
            "category": ["类别", "产品类别", "品类"],
            "month": ["月", "每月", "按月"],
        },
    )
