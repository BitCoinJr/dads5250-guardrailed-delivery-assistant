# Revenue analytics sample repository

This synthetic dbt project starts with a deliberately broad revenue definition: every order status contributes to revenue. Business users can request that selected statuses be excluded. The supported MVP scope is one metric, `revenue`, grouped by order date.

`seeds/orders.csv` feeds `models/staging/stg_orders.sql`, which feeds `models/marts/fct_revenue.sql`. The singular policy test, revenue documentation and one versioned BI dashboard definition must change together. `metadata/dependencies.json` records these downstream relationships. The assistant reads this source repository and applies proposed replacements only to a separate per-run copy.

All records are synthetic. The demo has no warehouse credentials or production connection. The source files never receive an approved change automatically.
