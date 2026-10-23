-- Optional: host the same app inside Snowsight (Streamlit in Snowflake).
-- 1. Upload app/streamlit_app.py, app/db.py, app/recall.py and app/environment.yml to the stage below
--    (Snowsight > Data > RECALLOPS.APP > Stages > APP_STAGE > + Files).
-- 2. Run this script.
USE SCHEMA RECALLOPS.APP;
CREATE STAGE IF NOT EXISTS APP_STAGE DIRECTORY = (ENABLE = TRUE);

-- Explicit runtime: the event account defaults to containers under BCR-2342.
CREATE OR REPLACE STREAMLIT RECALLOPS_APP
  FROM '@RECALLOPS.APP.APP_STAGE'
  MAIN_FILE = 'streamlit_app.py'
  QUERY_WAREHOUSE = DEFAULT_WH
  RUNTIME_NAME = 'SYSTEM$WAREHOUSE_RUNTIME'
  TITLE = 'RecallOps';

ALTER STREAMLIT RECALLOPS_APP ADD LIVE VERSION FROM LAST;
