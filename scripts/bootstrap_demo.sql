-- RecallOps browser-only bootstrap: paste this complete file into a Snowsight SQL worksheet.
-- Choose an authorized role and a running warehouse in the worksheet before running all statements.
-- Source: https://api.fda.gov/food/enforcement.json (food enforcement reports).
-- Retrieved 2,000 real reports; this compact fallback inserts ONLY 12 selected real reports.
-- The 6 locations, 49 stock quantities/rows, 10 orders, and control lots are generated demo data.
-- Existing table rows, cases, holds, and audit history are preserved; matching IDs are skipped.
-- For a fresh demo schema the expected counts are FDA_RECALLS=12, LOCATIONS=6, INVENTORY=49, ORDERS=10.
-- Setup creates missing objects and replaces the two procedure definitions; it does not call them.
-- No credentials, external integrations, model calls, warehouse creation, or account settings included.

-- RecallOps: Snowflake objects. Run with scripts/run_sql.py (or paste into a Snowsight worksheet).
CREATE DATABASE IF NOT EXISTS RECALLOPS;
CREATE SCHEMA IF NOT EXISTS RECALLOPS.APP;
USE SCHEMA RECALLOPS.APP;

-- Real FDA food enforcement reports (openFDA), loaded by scripts/load_fda.py
CREATE TABLE IF NOT EXISTS FDA_RECALLS (
  RECALL_NUMBER STRING PRIMARY KEY,
  EVENT_ID STRING,
  RECALLING_FIRM STRING,
  PRODUCT_DESCRIPTION STRING,
  CODE_INFO STRING,
  REASON_FOR_RECALL STRING,
  CLASSIFICATION STRING,
  DISTRIBUTION_PATTERN STRING,
  STATUS STRING,
  REPORT_DATE DATE,
  RAW VARIANT,
  LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Store locations of the grocery chain
CREATE TABLE IF NOT EXISTS LOCATIONS (
  LOCATION_ID STRING PRIMARY KEY,
  LOCATION_NAME STRING,
  LOCATION_TYPE STRING,   -- WAREHOUSE | STORE
  STATE STRING
);

-- Lot-level inventory. Product identity (UPC, name, firm, lot) comes from real FDA records.
CREATE TABLE IF NOT EXISTS INVENTORY (
  INVENTORY_ID STRING PRIMARY KEY,
  LOCATION_ID STRING,
  UPC STRING,
  PRODUCT_NAME STRING,
  FIRM STRING,
  LOT_CODE STRING,
  QUANTITY NUMBER,
  SOURCE_RECALL_NUMBER STRING   -- FDA record the product identity was taken from
);

CREATE TABLE IF NOT EXISTS ORDERS (
  ORDER_ID STRING PRIMARY KEY,
  INVENTORY_ID STRING,
  QUANTITY NUMBER,
  DESTINATION STRING,
  STATUS STRING DEFAULT 'PENDING',   -- PENDING | FULFILLED | BLOCKED
  UPDATED_AT TIMESTAMP_NTZ
);

-- One case per interpreted notice: original text, Claude output, reviewed scope
CREATE TABLE IF NOT EXISTS RECALL_CASES (
  CASE_ID STRING PRIMARY KEY,
  RECALL_NUMBER STRING,
  NOTICE_TEXT STRING,
  MODEL STRING,
  MODEL_OUTPUT VARIANT,
  REVIEWED_SCOPE VARIANT,
  STATUS STRING,            -- PROPOSED | APPROVED
  CREATED_BY STRING DEFAULT CURRENT_USER(),
  CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS HOLDS (
  INVENTORY_ID STRING,
  CASE_ID STRING,
  QUANTITY NUMBER,
  APPROVED_BY STRING,
  APPROVED_AT TIMESTAMP_NTZ,
  PRIMARY KEY (INVENTORY_ID, CASE_ID)
);

CREATE TABLE IF NOT EXISTS ACTIONS (
  ACTION_ID STRING DEFAULT UUID_STRING(),
  CASE_ID STRING,
  ACTION_TYPE STRING,   -- INTERPRETED | APPROVED | ORDER_BLOCKED | ORDER_FULFILLED
  DETAIL VARIANT,
  ACTOR STRING DEFAULT CURRENT_USER(),
  ACTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Approve: hold every inventory row matching the reviewed scope. Idempotent (MERGE).
CREATE OR REPLACE PROCEDURE APPROVE_HOLDS(CASE_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  n_new NUMBER;
  n_total NUMBER;
  qty NUMBER;
BEGIN
  MERGE INTO HOLDS h
  USING (
    SELECT i.INVENTORY_ID, i.QUANTITY
    FROM INVENTORY i, RECALL_CASES c
    WHERE c.CASE_ID = :CASE_ID
      AND ARRAY_CONTAINS(i.UPC::VARIANT, c.REVIEWED_SCOPE:upcs::ARRAY)
      AND i.LOT_CODE IS NOT NULL
      AND (ARRAY_SIZE(c.REVIEWED_SCOPE:lot_codes::ARRAY) = 0
           OR ARRAY_CONTAINS(UPPER(i.LOT_CODE)::VARIANT, c.REVIEWED_SCOPE:lot_codes::ARRAY))
  ) m
  ON h.INVENTORY_ID = m.INVENTORY_ID AND h.CASE_ID = :CASE_ID
  WHEN NOT MATCHED THEN INSERT (INVENTORY_ID, CASE_ID, QUANTITY, APPROVED_BY, APPROVED_AT)
    VALUES (m.INVENTORY_ID, :CASE_ID, m.QUANTITY, CURRENT_USER(), CURRENT_TIMESTAMP());
  n_new := SQLROWCOUNT;
  SELECT COUNT(*), COALESCE(SUM(QUANTITY), 0) INTO :n_total, :qty FROM HOLDS WHERE CASE_ID = :CASE_ID;
  UPDATE RECALL_CASES SET STATUS = 'APPROVED' WHERE CASE_ID = :CASE_ID;
  INSERT INTO ACTIONS (CASE_ID, ACTION_TYPE, DETAIL)
    SELECT :CASE_ID, 'APPROVED', OBJECT_CONSTRUCT('new_holds', :n_new, 'total_holds', :n_total, 'units', :qty);
  RETURN OBJECT_CONSTRUCT('new_holds', n_new, 'total_holds', n_total, 'units_held', qty);
END;
$$;

-- Fulfil an order only if its stock carries no approved hold.
CREATE OR REPLACE PROCEDURE FULFILL_ORDER(ORDER_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  hold_case STRING;
  result STRING;
BEGIN
  SELECT MAX(h.CASE_ID) INTO :hold_case
  FROM ORDERS o JOIN HOLDS h ON h.INVENTORY_ID = o.INVENTORY_ID
  WHERE o.ORDER_ID = :ORDER_ID;
  result := IFF(hold_case IS NULL, 'FULFILLED', 'BLOCKED');
  UPDATE ORDERS SET STATUS = :result, UPDATED_AT = CURRENT_TIMESTAMP() WHERE ORDER_ID = :ORDER_ID;
  INSERT INTO ACTIONS (CASE_ID, ACTION_TYPE, DETAIL)
    SELECT :hold_case, 'ORDER_' || :result, OBJECT_CONSTRUCT('order_id', :ORDER_ID);
  RETURN OBJECT_CONSTRUCT('order_id', ORDER_ID, 'result', result, 'hold_case', hold_case);
END;
$$;

-- Add 12 FDA_RECALLS rows; preserve rows with existing primary identifiers.
MERGE INTO FDA_RECALLS target
USING (
    SELECT column1::STRING AS RECALL_NUMBER,
           column2::STRING AS EVENT_ID,
           column3::STRING AS RECALLING_FIRM,
           column4::STRING AS PRODUCT_DESCRIPTION,
           column5::STRING AS CODE_INFO,
           column6::STRING AS REASON_FOR_RECALL,
           column7::STRING AS CLASSIFICATION,
           column8::STRING AS DISTRIBUTION_PATTERN,
           column9::STRING AS STATUS,
           TO_DATE(column10::STRING, 'YYYYMMDD') AS REPORT_DATE,
           PARSE_JSON(column11::STRING) AS RAW
    FROM VALUES
      ('H-0015-2027', '99933', 'QUESO PALMITA GP LLC', 'QUESO PALMITA. Generic Name: Pastel de Queso (Cheese Pie). Intended use: Human consumption. Condition: Frozen. Shelf life or expected life: 90 days. Type of packaging: Vacuum, resealable package. Net weight: 1.2 lbs. UPC: 094922980045.', 'Manufacturing code: PQ02. Batch/lot code: PQ-1-0024. Manufacturing date: 04/22/2026. Packing date: 04/22/2026. Best By: 10/22/2026. Expiration date: 10/22/2026.', 'Undeclared milk, cheese declared', 'Class II', 'Texas', 'Ongoing', '20261014', '{"status": "Ongoing", "city": "Stafford", "state": "TX", "country": "United States", "classification": "Class II", "openfda": {}, "product_type": "Food", "event_id": "99933", "recalling_firm": "QUESO PALMITA GP LLC", "address_1": "12853 Capricorn St", "address_2": "N/A", "postal_code": "77477-3911", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "Telephone", "distribution_pattern": "Texas", "recall_number": "H-0015-2027", "product_description": "QUESO PALMITA. Generic Name: Pastel de Queso (Cheese Pie). Intended use: Human consumption. Condition: Frozen. Shelf life or expected life: 90 days. Type of packaging: Vacuum, resealable package. Net weight: 1.2 lbs. UPC: 094922980045.", "product_quantity": "20 packages", "reason_for_recall": "Undeclared milk, cheese declared", "recall_initiation_date": "20260915", "center_classification_date": "20261007", "report_date": "20261014", "code_info": "Manufacturing code: PQ02. Batch/lot code: PQ-1-0024. Manufacturing date: 04/22/2026. Packing date: 04/22/2026. Best By: 10/22/2026. Expiration date: 10/22/2026."}'),
      ('H-0016-2027', '99872', 'A&P CREATIONS', 'X10 Natural Enhancement Supplement, 0.5 fl oz/sachet (15 mL), 7 sachets/box, UPC: 7708075247094, Manufactured by FutuPro S.A.S., Colombian Industry; Distributed by Natur Fuel, 2725 Armstrong Avenue, Clermont, FL 34714.', 'Lot # F090824LN16, Expiry: 8/2026; Lot # F170325LN19, Expiry: 03/2027; Lot # 300326LN28, Expiry: 03/2028.', 'Product contains undeclared Sildenafil and Tadalafil.', 'Class I', 'Distributed nationwide (US).', 'Ongoing', '20261014', '{"status": "Ongoing", "city": "Clermont", "state": "FL", "country": "United States", "classification": "Class I", "openfda": {}, "product_type": "Food", "event_id": "99872", "recalling_firm": "A&P CREATIONS", "address_1": "2725 Armstrong Ave", "address_2": "N/A", "postal_code": "34714-8117", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "Press Release", "distribution_pattern": "Distributed nationwide (US).", "recall_number": "H-0016-2027", "product_description": "X10 Natural Enhancement Supplement, 0.5 fl oz/sachet (15 mL), 7 sachets/box, UPC: 7708075247094, Manufactured by FutuPro S.A.S., Colombian Industry; Distributed by Natur Fuel, 2725 Armstrong Avenue, Clermont, FL 34714.", "product_quantity": "1,283 retail units", "reason_for_recall": "Product contains undeclared Sildenafil and Tadalafil.", "recall_initiation_date": "20260914", "center_classification_date": "20261007", "report_date": "20261014", "code_info": "Lot # F090824LN16, Expiry: 8/2026; Lot # F170325LN19, Expiry: 03/2027; Lot # 300326LN28, Expiry: 03/2028."}'),
      ('H-0007-2027', '99937', 'G L Mezzetta Inc', 'Mezzetta GOLDEN GREEK PEPERONCINI MEDIUM HEAT 32 FL OZ  G.L. MEZZETTA, INC.,  AMERICAN CANYON, NAPA VALLEY, CA 94503  PRODUCT OF GREECE  UPC: 073214003280', 'Lots: 720106. Best if used by: July 2029.', 'Potential contamination with foreign objects: mice.', 'Class II', 'Domestic: AZ, CA, CO, GA, IA, ID, IL, IN, MI, MN, MO, NC, OH, OK, OR, PA, SD, TX, UT, VA, WA, WI. Foreign: Not applicable.', 'Ongoing', '20261014', '{"status": "Ongoing", "city": "American Canyon", "state": "CA", "country": "United States", "classification": "Class II", "openfda": {}, "product_type": "Food", "event_id": "99937", "recalling_firm": "G L Mezzetta Inc", "address_1": "105 Mezzetta Ct", "address_2": "N/A", "postal_code": "94503-9604", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "Letter", "distribution_pattern": "Domestic: AZ, CA, CO, GA, IA, ID, IL, IN, MI, MN, MO, NC, OH, OK, OR, PA, SD, TX, UT, VA, WA, WI. Foreign: Not applicable.", "recall_number": "H-0007-2027", "product_description": "Mezzetta GOLDEN GREEK PEPERONCINI MEDIUM HEAT 32 FL OZ  G.L. MEZZETTA, INC.,  AMERICAN CANYON, NAPA VALLEY, CA 94503  PRODUCT OF GREECE  UPC: 073214003280", "product_quantity": "7,497 cases (6 units/case)", "reason_for_recall": "Potential contamination with foreign objects: mice.", "recall_initiation_date": "20260919", "center_classification_date": "20261002", "report_date": "20261014", "code_info": "Lots: 720106. Best if used by: July 2029."}'),
      ('H-0011-2027', '99686', 'The Better Bakehouse Snack Company', 'Donutful Chocolate Dipped Vanilla Cake Donuts - 7.05oz/10ct.Case Configuration   5 count carton, 6 cartons per case. UPC 850041392103. Paperboard carton containing 5 individually wrapped packages of two donuts each. UPC: 850041392103. The Better Bakehouse Snack Co.  3651 Lindell Rd, Suite D700  Las Vegas, NV 89103', 'Lot # 26078 BEST BY: 09/15/2026', 'Undeclared Milk.', 'Class I', 'Product was distributed nationwide.', 'Ongoing', '20261014', '{"status": "Ongoing", "city": "Las Vegas", "state": "NV", "country": "United States", "classification": "Class I", "openfda": {}, "product_type": "Food", "event_id": "99686", "recalling_firm": "The Better Bakehouse Snack Company", "address_1": "3651 Lindell Road, Suite D700", "address_2": "N/A", "postal_code": "89103", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "Two or more of the following: Email, Fax, Letter, Press Release, Telephone, Visit", "distribution_pattern": "Product was distributed nationwide.", "recall_number": "H-0011-2027", "product_description": "Donutful Chocolate Dipped Vanilla Cake Donuts - 7.05oz/10ct.Case Configuration   5 count carton, 6 cartons per case. UPC 850041392103. Paperboard carton containing 5 individually wrapped packages of two donuts each. UPC: 850041392103. The Better Bakehouse Snack Co.  3651 Lindell Rd, Suite D700  Las Vegas, NV 89103", "product_quantity": "10,602 consumer units", "reason_for_recall": "Undeclared Milk.", "recall_initiation_date": "20260817", "center_classification_date": "20261006", "report_date": "20261014", "code_info": "Lot # 26078 BEST BY: 09/15/2026"}'),
      ('H-1397-2026', '99735', 'Admiral Beverage Corporation', '7up Tropical beverage, shelf stable, 12oz can in a 12pk wrap, labeled as 7 up Tropical Beverage containing cans that are labeled as 7Up Tropical Zero Sugar which contain full sugar soda. 12 fl oz, UPC: 0 78000 03798 2, Dr Pepper/Seven Up, Inc., 6425 Hall of Fame Lane, Frisco TX 75034.', 'Lot Code/Batch Code: UT06176 Packing Code (Best By): March 17, 2027', 'Product may contain undeclared sugar.', 'Class II', 'Product was distributed to Utah.', 'Completed', '20261007', '{"status": "Completed", "city": "Pleasant View", "state": "UT", "country": "United States", "classification": "Class II", "openfda": {}, "product_type": "Food", "event_id": "99735", "recalling_firm": "Admiral Beverage Corporation", "address_1": "2751 N 1000 W", "address_2": "", "postal_code": "84414-2144", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "E-Mail", "distribution_pattern": "Product was distributed to Utah.", "recall_number": "H-1397-2026", "product_description": "7up Tropical beverage, shelf stable, 12oz can in a 12pk wrap, labeled as 7 up Tropical Beverage containing cans that are labeled as 7Up Tropical Zero Sugar which contain full sugar soda. 12 fl oz, UPC: 0 78000 03798 2, Dr Pepper/Seven Up, Inc., 6425 Hall of Fame Lane, Frisco TX 75034.", "product_quantity": "3,240 cases=77,760 cans", "reason_for_recall": "Product may contain undeclared sugar.", "recall_initiation_date": "20260820", "center_classification_date": "20260929", "report_date": "20261007", "code_info": "Lot Code/Batch Code: UT06176 Packing Code (Best By): March 17, 2027", "more_code_info": ""}'),
      ('H-1403-2026', '98954', 'Coco G''s Snack Foods, Inc.', 'Coco G''s Courmet Flaming Cheddar Hots, Spicy Cheddar Cheese Popcorn.  Packaged in the following sized plastic bags:   1.  2.5 oz (81g), UPC 6 94161-25911 9.   2.  4.15 oz (118g), UPC 6 94161-38911 3.   3.  5 oz (142g), UPC 6 94161-60005 8.    761 Commerce Dr. Unit F, Union Grove, WI  53182', 'Lot Numbers:007560   Best By June 10, 2026', 'Potential Salmonella contamination.', 'Class I', 'IL, WI', 'Ongoing', '20261007', '{"status": "Ongoing", "city": "Union Grove", "state": "WI", "country": "United States", "classification": "Class I", "openfda": {}, "product_type": "Food", "event_id": "98954", "recalling_firm": "Coco G''s Snack Foods, Inc.", "address_1": "761 Commerce Dr Ste F", "address_2": "", "postal_code": "53182-1079", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "E-Mail", "distribution_pattern": "IL, WI", "recall_number": "H-1403-2026", "product_description": "Coco G''s Courmet Flaming Cheddar Hots, Spicy Cheddar Cheese Popcorn.  Packaged in the following sized plastic bags:   1.  2.5 oz (81g), UPC 6 94161-25911 9.   2.  4.15 oz (118g), UPC 6 94161-38911 3.   3.  5 oz (142g), UPC 6 94161-60005 8.    761 Commerce Dr. Unit F, Union Grove, WI  53182", "product_quantity": "270 bags", "reason_for_recall": "Potential Salmonella contamination.", "recall_initiation_date": "20260505", "center_classification_date": "20260929", "report_date": "20261007", "code_info": "Lot Numbers:007560   Best By June 10, 2026", "more_code_info": ""}'),
      ('H-1339-2026', '99737', 'Everything Sprouts, LLC', 'Everything Sprouts Crunchy Protein Sprout Mix, containing Alfalfa Fenugreek, Cabbage, Mung, Adzuki, Lentils, Green Pea, Net Wt. 5.0 oz (142 g) UPC 0 87906-01018 7.  everythingsprouts.com', 'Lot# 222, 223, 226, 230', 'Sprouts may be contaminated with STEC E. coli and/or Salmonella.', 'Class I', 'MN, WI', 'Ongoing', '20260923', '{"status": "Ongoing", "city": "Minneapolis", "state": "MN", "country": "United States", "classification": "Class I", "openfda": {}, "product_type": "Food", "event_id": "99737", "recalling_firm": "Everything Sprouts, LLC", "address_1": "2751 Minnehaha Ave", "address_2": "N/A", "postal_code": "55406-1546", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "Two or more of the following: Email, Fax, Letter, Press Release, Telephone, Visit", "distribution_pattern": "MN, WI", "recall_number": "H-1339-2026", "product_description": "Everything Sprouts Crunchy Protein Sprout Mix, containing Alfalfa Fenugreek, Cabbage, Mung, Adzuki, Lentils, Green Pea, Net Wt. 5.0 oz (142 g) UPC 0 87906-01018 7.  everythingsprouts.com", "product_quantity": "201.56 pounds", "reason_for_recall": "Sprouts may be contaminated with STEC E. coli and/or Salmonella.", "recall_initiation_date": "20260822", "center_classification_date": "20260914", "report_date": "20260923", "code_info": "Lot# 222, 223, 226, 230", "more_code_info": ""}'),
      ('H-1386-2026', '99803', 'Best Friends Bakery, LLC', 'PUMPKIN SPICE NO BAKE COOKIE NET WT 3.5 oz. INGREDIENTS: WHOLE GRAIN OATS, MILK, MARGARINE***WATER, SALT, CONTAINS LESS THAN 2% OF THE FOLLOWING: SOY LECITHIN, VEGETABLE MONO & DIGLYCERIDES, POTASSIUM SORBATE***, CITRIC ACID, NATURAL & ARTIFICIAL FLAVOR, BETA CAROTENE, VITAMIN A PALMITATE ADDED, PEANUT BUTTER***VANILLA***PUMPKIN PIE SPICE***GLYCERINE, PAPRIKA OLEORESINM, POTASSIUM SORBATE CONTAINS: EGG, MILK, SOY, WHEAT MADE IN A FACILITY WITH PEANUTS AND TREE NUTS UPC 8 10158 14087 5 Michelle''s Bakery 101 Fashion Ave Connelly Springs, NC 28612', 'Lot 20326', 'Peanuts & Eggs. The firm list peanuts in the ingredient statement but omitted them from the contain statement. They also have eggs listed in the contain statement but there are no eggs in the product.', 'Class II', 'Product was shipped to the following states: AL, FL, GA, IN, KY, MI, OH, TN, VA &  WV.', 'Ongoing', '20260923', '{"status": "Ongoing", "city": "Connelly Springs", "state": "NC", "country": "United States", "classification": "Class II", "openfda": {}, "product_type": "Food", "event_id": "99803", "recalling_firm": "Best Friends Bakery, LLC", "address_1": "101 Fashion Ave", "address_2": "N/A", "postal_code": "28612-7483", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "E-Mail", "distribution_pattern": "Product was shipped to the following states: AL, FL, GA, IN, KY, MI, OH, TN, VA &  WV.", "recall_number": "H-1386-2026", "product_description": "PUMPKIN SPICE NO BAKE COOKIE NET WT 3.5 oz. INGREDIENTS: WHOLE GRAIN OATS, MILK, MARGARINE***WATER, SALT, CONTAINS LESS THAN 2% OF THE FOLLOWING: SOY LECITHIN, VEGETABLE MONO & DIGLYCERIDES, POTASSIUM SORBATE***, CITRIC ACID, NATURAL & ARTIFICIAL FLAVOR, BETA CAROTENE, VITAMIN A PALMITATE ADDED, PEANUT BUTTER***VANILLA***PUMPKIN PIE SPICE***GLYCERINE, PAPRIKA OLEORESINM, POTASSIUM SORBATE CONTAINS: EGG, MILK, SOY, WHEAT MADE IN A FACILITY WITH PEANUTS AND TREE NUTS UPC 8 10158 14087 5 Michelle''s Bakery 101 Fashion Ave Connelly Springs, NC 28612", "product_quantity": "1,416/3.5oz cookies", "reason_for_recall": "Peanuts & Eggs. The firm list peanuts in the ingredient statement but omitted them from the contain statement. They also have eggs listed in the contain statement but there are no eggs in the product.", "recall_initiation_date": "20260817", "center_classification_date": "20260916", "report_date": "20260923", "code_info": "Lot 20326", "more_code_info": ""}'),
      ('H-1335-2026', '99675', 'L-Nutra Inc', 'Prolon Everyday Apulian Almond & Cocoa Spread, NET WT: 8.47 OZ. Product packaged in glass jar with white label and gold screw on closure. UPC: 50040360530', 'Lot code: L2755 Expiration: 02 Jan 2027', 'Undeclared allergen (tree nuts): hazelnut, cashew, and pistachio.', 'Class II', 'Product is sold exclusively from the recalling firm''s online website nationwide.', 'Ongoing', '20260916', '{"status": "Ongoing", "city": "Los Angeles", "state": "CA", "country": "United States", "classification": "Class II", "openfda": {}, "product_type": "Food", "event_id": "99675", "recalling_firm": "L-Nutra Inc", "address_1": "600 Corporate Pointe Ste 1200", "address_2": "", "postal_code": "90230-7626", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "E-Mail", "distribution_pattern": "Product is sold exclusively from the recalling firm''s online website nationwide.", "recall_number": "H-1335-2026", "product_description": "Prolon Everyday Apulian Almond & Cocoa Spread, NET WT: 8.47 OZ. Product packaged in glass jar with white label and gold screw on closure. UPC: 50040360530", "product_quantity": "8,529 jars", "reason_for_recall": "Undeclared allergen (tree nuts): hazelnut, cashew, and pistachio.", "recall_initiation_date": "20260807", "center_classification_date": "20260910", "report_date": "20260916", "code_info": "Lot code: L2755 Expiration: 02 Jan 2027", "more_code_info": ""}'),
      ('H-1309-2026', '99656', 'THE HAMPTON GROCER', 'THE HAMPTON GROCER brand; Lacnola; SMALL BATCH LACTATION GRANOLA, 8oz, stand up pouches; NUTRIENT DENSE INGREDIENTS + MORINGA; SUPPORTS + PROMOTES HEALTHY LACTATION; INGREDIENTS Organic Gluten Free Oats Organic Maple Syrup Organic Pumpkin Seeds Organic Coconut Oil Almond Butter Almonds Organic Coconut Sugar Chocolate Chips (Cane Sugar, Unsweetened Chocolate, Cocoa Butter) Organic Ground Flaxseed Moringa Leaf Powder Pure Vanilla Extract (Water, Alcohol, Vanilla Bean Extractives) Cream of Tartar Baking Soda Salt; CONTAINS: TREE NUTS (ALMOND, COCONUTS); DISTRIBUTED BY: The Hampton Grocer Inc. Montauk, NY; MADE IN A FACILITY THAT PROCESSES TREE NUTS, PEANUTS, SESAME, AND SOY; UPC 8 50035 32455 4', 'Lot Code HGLC-102125 with expiration date 21OCT2026 Lot Code HGLC-021326 with expiration date 13FEB2027', 'Product may be contaminated with Salmonella.', 'Class I', 'Nationwide', 'Ongoing', '20260909', '{"status": "Ongoing", "city": "Montauk", "state": "NY", "country": "United States", "classification": "Class I", "openfda": {}, "product_type": "Food", "event_id": "99656", "recalling_firm": "THE HAMPTON GROCER", "address_1": "46 Gilbert Rd", "address_2": "N/A", "postal_code": "11954-5095", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "Two or more of the following: Email, Fax, Letter, Press Release, Telephone, Visit", "distribution_pattern": "Nationwide", "recall_number": "H-1309-2026", "product_description": "THE HAMPTON GROCER brand; Lacnola; SMALL BATCH LACTATION GRANOLA, 8oz, stand up pouches; NUTRIENT DENSE INGREDIENTS + MORINGA; SUPPORTS + PROMOTES HEALTHY LACTATION; INGREDIENTS Organic Gluten Free Oats Organic Maple Syrup Organic Pumpkin Seeds Organic Coconut Oil Almond Butter Almonds Organic Coconut Sugar Chocolate Chips (Cane Sugar, Unsweetened Chocolate, Cocoa Butter) Organic Ground Flaxseed Moringa Leaf Powder Pure Vanilla Extract (Water, Alcohol, Vanilla Bean Extractives) Cream of Tartar Baking Soda Salt; CONTAINS: TREE NUTS (ALMOND, COCONUTS); DISTRIBUTED BY: The Hampton Grocer Inc. Montauk, NY; MADE IN A FACILITY THAT PROCESSES TREE NUTS, PEANUTS, SESAME, AND SOY; UPC 8 50035 32455 4", "product_quantity": "4,059 units", "reason_for_recall": "Product may be contaminated with Salmonella.", "recall_initiation_date": "20260814", "center_classification_date": "20260828", "report_date": "20260909", "code_info": "Lot Code HGLC-102125 with expiration date 21OCT2026 Lot Code HGLC-021326 with expiration date 13FEB2027", "more_code_info": ""}'),
      ('H-1258-2026', '99571', 'H & U Inc. dba Sun Noodle', 'Sura Tanmen Hot and Sour Flavor Premium Japanese Noodles & Soup Base. Retail package net wt. 15.4oz. Product is ramen noodle kit which contains noodles and Soba soup packet.   Item #05410 retail package, UPC 085315054108 Item #05410.1 cardboard box (12 packages per case), UPC 085315054105  Product is Perishable Frozen or Refrigerated and made by Sun Noodle Hawaii 1933 Colburn Street, Honolulu, HI', 'Production Lot: 1226183  Products will be dated for expiration according to their date of defrost by retailer or distributor in the following format: MM/DD', 'Soba sauce packet, which contains bonito, sardine, and mackerel (fish), was packed into Sura Tanmen Hot and Sour Flavor ramen noodle package kit, but fish species are not declared on finished product label.', 'Class I', 'Distribute in HI.', 'Terminated', '20260902', '{"status": "Terminated", "city": "Honolulu", "state": "HI", "country": "United States", "classification": "Class I", "openfda": {}, "product_type": "Food", "event_id": "99571", "recalling_firm": "H & U Inc. dba Sun Noodle", "address_1": "1933 Colburn St", "address_2": "N/A", "postal_code": "96819-3248", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "Two or more of the following: Email, Fax, Letter, Press Release, Telephone, Visit", "distribution_pattern": "Distribute in HI.", "recall_number": "H-1258-2026", "product_description": "Sura Tanmen Hot and Sour Flavor Premium Japanese Noodles & Soup Base. Retail package net wt. 15.4oz. Product is ramen noodle kit which contains noodles and Soba soup packet.   Item #05410 retail package, UPC 085315054108 Item #05410.1 cardboard box (12 packages per case), UPC 085315054105  Product is Perishable Frozen or Refrigerated and made by Sun Noodle Hawaii 1933 Colburn Street, Honolulu, HI", "product_quantity": "140 packages", "reason_for_recall": "Soba sauce packet, which contains bonito, sardine, and mackerel (fish), was packed into Sura Tanmen Hot and Sour Flavor ramen noodle package kit, but fish species are not declared on finished product label.", "recall_initiation_date": "20260804", "center_classification_date": "20260821", "termination_date": "20260827", "report_date": "20260902", "code_info": "Production Lot: 1226183  Products will be dated for expiration according to their date of defrost by retailer or distributor in the following format: MM/DD"}'),
      ('H-1275-2026', '99493', 'Lidl US TRADING', 'ERIDANOUS GREEK STYLE Shortbread Cookies with apricot filling and cocoa topping with coconut sprinkles. Product is packed onto a plastic carton tray with outer paper sleeve, 330 g (weight), UPC: 4056489125846.', 'BEST BEFORE: 10/11/2026 LOT NO: 260315', 'The firm discovered that certain units shipped to the U.S. retail stores only has "foreign languages" on the label. Product has undeclared wheat, soy, milk, eggs and tree nut (coconut).', 'Class II', 'Product was shipped to the following states: DC, DE, GA, MD, NJ, NY, NC, PA, SC, &  VA.', 'Ongoing', '20260902', '{"status": "Ongoing", "city": "Arlington", "state": "VA", "country": "United States", "classification": "Class II", "openfda": {}, "product_type": "Food", "event_id": "99493", "recalling_firm": "Lidl US TRADING", "address_1": "3500 S Clark Pl", "address_2": "N/A", "postal_code": "22202", "voluntary_mandated": "Voluntary: Firm initiated", "initial_firm_notification": "E-Mail", "distribution_pattern": "Product was shipped to the following states: DC, DE, GA, MD, NJ, NY, NC, PA, SC, &  VA.", "recall_number": "H-1275-2026", "product_description": "ERIDANOUS GREEK STYLE Shortbread Cookies with apricot filling and cocoa topping with coconut sprinkles. Product is packed onto a plastic carton tray with outer paper sleeve, 330 g (weight), UPC: 4056489125846.", "product_quantity": "200 units", "reason_for_recall": "The firm discovered that certain units shipped to the U.S. retail stores only has \\"foreign languages\\" on the label. Product has undeclared wheat, soy, milk, eggs and tree nut (coconut).", "recall_initiation_date": "20260722", "center_classification_date": "20260826", "report_date": "20260902", "code_info": "BEST BEFORE: 10/11/2026 LOT NO: 260315"}')
) source
ON target.RECALL_NUMBER = source.RECALL_NUMBER
WHEN NOT MATCHED THEN INSERT (RECALL_NUMBER, EVENT_ID, RECALLING_FIRM, PRODUCT_DESCRIPTION, CODE_INFO, REASON_FOR_RECALL, CLASSIFICATION, DISTRIBUTION_PATTERN, STATUS, REPORT_DATE, RAW)
VALUES (source.RECALL_NUMBER, source.EVENT_ID, source.RECALLING_FIRM, source.PRODUCT_DESCRIPTION, source.CODE_INFO, source.REASON_FOR_RECALL, source.CLASSIFICATION, source.DISTRIBUTION_PATTERN, source.STATUS, source.REPORT_DATE, source.RAW);

-- Add 6 LOCATIONS rows; preserve rows with existing primary identifiers.
MERGE INTO LOCATIONS target
USING (
    SELECT column1::STRING AS LOCATION_ID,
           column2::STRING AS LOCATION_NAME,
           column3::STRING AS LOCATION_TYPE,
           column4::STRING AS STATE
    FROM VALUES
      ('WH-1', 'Central Warehouse', 'WAREHOUSE', 'CA'),
      ('ST-1', 'Store 1 - Oakland', 'STORE', 'CA'),
      ('ST-2', 'Store 2 - San Jose', 'STORE', 'CA'),
      ('ST-3', 'Store 3 - Fresno', 'STORE', 'CA'),
      ('ST-4', 'Store 4 - Sacramento', 'STORE', 'CA'),
      ('ST-5', 'Store 5 - Los Angeles', 'STORE', 'CA')
) source
ON target.LOCATION_ID = source.LOCATION_ID
WHEN NOT MATCHED THEN INSERT (LOCATION_ID, LOCATION_NAME, LOCATION_TYPE, STATE)
VALUES (source.LOCATION_ID, source.LOCATION_NAME, source.LOCATION_TYPE, source.STATE);

-- Add 49 INVENTORY rows; preserve rows with existing primary identifiers.
MERGE INTO INVENTORY target
USING (
    SELECT column1::STRING AS INVENTORY_ID,
           column2::STRING AS LOCATION_ID,
           column3::STRING AS UPC,
           column4::STRING AS PRODUCT_NAME,
           column5::STRING AS FIRM,
           column6::STRING AS LOT_CODE,
           column7::NUMBER AS QUANTITY,
           column8::STRING AS SOURCE_RECALL_NUMBER
    FROM VALUES
      ('INV-0001', 'WH-1', '094922980045', 'QUESO PALMITA', 'QUESO PALMITA GP LLC', 'PQ-1-0024', 34, 'H-0015-2027'),
      ('INV-0002', 'ST-2', '094922980045', 'QUESO PALMITA', 'QUESO PALMITA GP LLC', 'PQ-1-0024', 100, 'H-0015-2027'),
      ('INV-0003', 'ST-4', '094922980045', 'QUESO PALMITA', 'QUESO PALMITA GP LLC', 'PQ-1-0029', 60, 'H-0015-2027'),
      ('INV-0004', 'WH-1', '094922980045', 'QUESO PALMITA', 'QUESO PALMITA GP LLC', NULL, 9, 'H-0015-2027'),
      ('INV-0005', 'ST-1', '7708075247094', 'X10 Natural Enhancement Supplement', 'A&P CREATIONS', '300326LN28', 83, 'H-0016-2027'),
      ('INV-0006', 'ST-5', '7708075247094', 'X10 Natural Enhancement Supplement', 'A&P CREATIONS', 'F090824LN16', 77, 'H-0016-2027'),
      ('INV-0007', 'ST-5', '7708075247094', 'X10 Natural Enhancement Supplement', 'A&P CREATIONS', '300326LN29', 95, 'H-0016-2027'),
      ('INV-0008', 'ST-4', '7708075247094', 'X10 Natural Enhancement Supplement', 'A&P CREATIONS', NULL, 59, 'H-0016-2027'),
      ('INV-0009', 'ST-3', '073214003280', 'Mezzetta GOLDEN GREEK PEPERONCINI MEDIUM HEAT 32 FL OZ  G.L', 'G L Mezzetta Inc', '720106', 109, 'H-0007-2027'),
      ('INV-0010', 'ST-4', '073214003280', 'Mezzetta GOLDEN GREEK PEPERONCINI MEDIUM HEAT 32 FL OZ  G.L', 'G L Mezzetta Inc', '720106', 103, 'H-0007-2027'),
      ('INV-0011', 'ST-2', '073214003280', 'Mezzetta GOLDEN GREEK PEPERONCINI MEDIUM HEAT 32 FL OZ  G.L', 'G L Mezzetta Inc', '720109', 41, 'H-0007-2027'),
      ('INV-0012', 'ST-1', '073214003280', 'Mezzetta GOLDEN GREEK PEPERONCINI MEDIUM HEAT 32 FL OZ  G.L', 'G L Mezzetta Inc', NULL, 33, 'H-0007-2027'),
      ('INV-0013', 'WH-1', '850041392103', 'Donutful Chocolate Dipped Vanilla Cake Donuts - 7.05oz/10ct.', 'The Better Bakehouse Snack Company', '26078', 51, 'H-0011-2027'),
      ('INV-0014', 'ST-5', '850041392103', 'Donutful Chocolate Dipped Vanilla Cake Donuts - 7.05oz/10ct.', 'The Better Bakehouse Snack Company', '26078', 83, 'H-0011-2027'),
      ('INV-0015', 'ST-3', '850041392103', 'Donutful Chocolate Dipped Vanilla Cake Donuts - 7.05oz/10ct.', 'The Better Bakehouse Snack Company', '26078', 109, 'H-0011-2027'),
      ('INV-0016', 'ST-4', '850041392103', 'Donutful Chocolate Dipped Vanilla Cake Donuts - 7.05oz/10ct.', 'The Better Bakehouse Snack Company', '26079', 21, 'H-0011-2027'),
      ('INV-0017', 'WH-1', '078000037982', '7up Tropical beverage', 'Admiral Beverage Corporation', 'UT06176', 79, 'H-1397-2026'),
      ('INV-0018', 'ST-4', '078000037982', '7up Tropical beverage', 'Admiral Beverage Corporation', 'UT06176', 96, 'H-1397-2026'),
      ('INV-0019', 'ST-2', '078000037982', '7up Tropical beverage', 'Admiral Beverage Corporation', 'UT06176', 11, 'H-1397-2026'),
      ('INV-0020', 'WH-1', '078000037982', '7up Tropical beverage', 'Admiral Beverage Corporation', 'UT06179', 115, 'H-1397-2026'),
      ('INV-0021', 'WH-1', '694161259119', 'Coco G''s Courmet Flaming Cheddar Hots', 'Coco G''s Snack Foods, Inc.', '007560', 64, 'H-1403-2026'),
      ('INV-0022', 'ST-3', '694161259119', 'Coco G''s Courmet Flaming Cheddar Hots', 'Coco G''s Snack Foods, Inc.', '007560', 26, 'H-1403-2026'),
      ('INV-0023', 'ST-1', '694161259119', 'Coco G''s Courmet Flaming Cheddar Hots', 'Coco G''s Snack Foods, Inc.', '007569', 91, 'H-1403-2026'),
      ('INV-0024', 'ST-5', '694161259119', 'Coco G''s Courmet Flaming Cheddar Hots', 'Coco G''s Snack Foods, Inc.', '007569', 93, 'H-1403-2026'),
      ('INV-0025', 'ST-4', '087906010187', 'Everything Sprouts Crunchy Protein Sprout Mix', 'Everything Sprouts, LLC', '226', 99, 'H-1339-2026'),
      ('INV-0026', 'ST-1', '087906010187', 'Everything Sprouts Crunchy Protein Sprout Mix', 'Everything Sprouts, LLC', '222', 26, 'H-1339-2026'),
      ('INV-0027', 'ST-2', '087906010187', 'Everything Sprouts Crunchy Protein Sprout Mix', 'Everything Sprouts, LLC', '229', 87, 'H-1339-2026'),
      ('INV-0028', 'ST-4', '087906010187', 'Everything Sprouts Crunchy Protein Sprout Mix', 'Everything Sprouts, LLC', '229', 34, 'H-1339-2026'),
      ('INV-0029', 'WH-1', '810158140875', 'PUMPKIN SPICE NO BAKE COOKIE NET WT 3.5 oz', 'Best Friends Bakery, LLC', '20326', 57, 'H-1386-2026'),
      ('INV-0030', 'ST-1', '810158140875', 'PUMPKIN SPICE NO BAKE COOKIE NET WT 3.5 oz', 'Best Friends Bakery, LLC', '20326', 14, 'H-1386-2026'),
      ('INV-0031', 'ST-5', '810158140875', 'PUMPKIN SPICE NO BAKE COOKIE NET WT 3.5 oz', 'Best Friends Bakery, LLC', '20326', 78, 'H-1386-2026'),
      ('INV-0032', 'ST-5', '810158140875', 'PUMPKIN SPICE NO BAKE COOKIE NET WT 3.5 oz', 'Best Friends Bakery, LLC', '20329', 69, 'H-1386-2026'),
      ('INV-0033', 'ST-5', '810158140875', 'PUMPKIN SPICE NO BAKE COOKIE NET WT 3.5 oz', 'Best Friends Bakery, LLC', '20329', 64, 'H-1386-2026'),
      ('INV-0034', 'ST-2', '50040360530', 'Prolon Everyday Apulian Almond & Cocoa Spread', 'L-Nutra Inc', 'L2755', 101, 'H-1335-2026'),
      ('INV-0035', 'ST-1', '50040360530', 'Prolon Everyday Apulian Almond & Cocoa Spread', 'L-Nutra Inc', 'L2755', 101, 'H-1335-2026'),
      ('INV-0036', 'ST-2', '50040360530', 'Prolon Everyday Apulian Almond & Cocoa Spread', 'L-Nutra Inc', 'L2759', 34, 'H-1335-2026'),
      ('INV-0037', 'ST-4', '50040360530', 'Prolon Everyday Apulian Almond & Cocoa Spread', 'L-Nutra Inc', 'L2759', 69, 'H-1335-2026'),
      ('INV-0038', 'WH-1', '850035324554', 'THE HAMPTON GROCER brand', 'THE HAMPTON GROCER', 'HGLC-102125', 86, 'H-1309-2026'),
      ('INV-0039', 'ST-5', '850035324554', 'THE HAMPTON GROCER brand', 'THE HAMPTON GROCER', 'HGLC-102125', 107, 'H-1309-2026'),
      ('INV-0040', 'ST-3', '850035324554', 'THE HAMPTON GROCER brand', 'THE HAMPTON GROCER', 'HGLC-102129', 54, 'H-1309-2026'),
      ('INV-0041', 'ST-4', '850035324554', 'THE HAMPTON GROCER brand', 'THE HAMPTON GROCER', 'HGLC-021329', 38, 'H-1309-2026'),
      ('INV-0042', 'ST-5', '085315054108', 'Sura Tanmen Hot and Sour Flavor Premium Japanese Noodles & S', 'H & U Inc. dba Sun Noodle', '1226183', 104, 'H-1258-2026'),
      ('INV-0043', 'WH-1', '085315054108', 'Sura Tanmen Hot and Sour Flavor Premium Japanese Noodles & S', 'H & U Inc. dba Sun Noodle', '1226183', 20, 'H-1258-2026'),
      ('INV-0044', 'ST-1', '085315054108', 'Sura Tanmen Hot and Sour Flavor Premium Japanese Noodles & S', 'H & U Inc. dba Sun Noodle', '1226189', 64, 'H-1258-2026'),
      ('INV-0045', 'ST-5', '085315054108', 'Sura Tanmen Hot and Sour Flavor Premium Japanese Noodles & S', 'H & U Inc. dba Sun Noodle', '1226189', 118, 'H-1258-2026'),
      ('INV-0046', 'ST-4', '4056489125846', 'ERIDANOUS GREEK STYLE Shortbread Cookies with apricot fillin', 'Lidl US TRADING', '260315', 113, 'H-1275-2026'),
      ('INV-0047', 'ST-1', '4056489125846', 'ERIDANOUS GREEK STYLE Shortbread Cookies with apricot fillin', 'Lidl US TRADING', '260315', 25, 'H-1275-2026'),
      ('INV-0048', 'WH-1', '4056489125846', 'ERIDANOUS GREEK STYLE Shortbread Cookies with apricot fillin', 'Lidl US TRADING', '260315', 103, 'H-1275-2026'),
      ('INV-0049', 'ST-4', '4056489125846', 'ERIDANOUS GREEK STYLE Shortbread Cookies with apricot fillin', 'Lidl US TRADING', '260319', 47, 'H-1275-2026')
) source
ON target.INVENTORY_ID = source.INVENTORY_ID
WHEN NOT MATCHED THEN INSERT (INVENTORY_ID, LOCATION_ID, UPC, PRODUCT_NAME, FIRM, LOT_CODE, QUANTITY, SOURCE_RECALL_NUMBER)
VALUES (source.INVENTORY_ID, source.LOCATION_ID, source.UPC, source.PRODUCT_NAME, source.FIRM, source.LOT_CODE, source.QUANTITY, source.SOURCE_RECALL_NUMBER);

-- Add 10 ORDERS rows; preserve rows with existing primary identifiers.
MERGE INTO ORDERS target
USING (
    SELECT column1::STRING AS ORDER_ID,
           column2::STRING AS INVENTORY_ID,
           column3::NUMBER AS QUANTITY,
           column4::STRING AS DESTINATION,
           column5::STRING AS STATUS
    FROM VALUES
      ('O-101', 'INV-0026', 7, 'Store 5 - Los Angeles', 'PENDING'),
      ('O-102', 'INV-0049', 47, 'Customer pickup', 'PENDING'),
      ('O-103', 'INV-0017', 26, 'Customer pickup', 'PENDING'),
      ('O-104', 'INV-0007', 40, 'Store 4 - Sacramento', 'PENDING'),
      ('O-105', 'INV-0019', 11, 'Customer pickup', 'PENDING'),
      ('O-106', 'INV-0014', 48, 'Store 4 - Sacramento', 'PENDING'),
      ('O-107', 'INV-0011', 34, 'Store 4 - Sacramento', 'PENDING'),
      ('O-108', 'INV-0006', 16, 'Store 2 - San Jose', 'PENDING'),
      ('O-109', 'INV-0001', 15, 'Store 1 - Oakland', 'PENDING'),
      ('O-110', 'INV-0027', 44, 'Store 1 - Oakland', 'PENDING')
) source
ON target.ORDER_ID = source.ORDER_ID
WHEN NOT MATCHED THEN INSERT (ORDER_ID, INVENTORY_ID, QUANTITY, DESTINATION, STATUS)
VALUES (source.ORDER_ID, source.INVENTORY_ID, source.QUANTITY, source.DESTINATION, source.STATUS);

-- Actual counts in this schema (existing data may make these larger).
SELECT 'FDA_RECALLS' AS TABLE_NAME, COUNT(*) AS ROW_COUNT FROM FDA_RECALLS
UNION ALL SELECT 'LOCATIONS', COUNT(*) FROM LOCATIONS
UNION ALL SELECT 'INVENTORY', COUNT(*) FROM INVENTORY
UNION ALL SELECT 'ORDERS', COUNT(*) FROM ORDERS;
