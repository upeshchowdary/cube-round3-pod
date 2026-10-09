# Real product photos: Pack and Returns test units

Ten units from the Round 2 Returns Manager test set (`returns_input_50.csv`). The photos are real product photos from
Wikimedia Commons: catalogue-style pictures of each product, not photos of an actual shipment or returned item. The
orders and scenarios are synthetic test cases with no customer data.

- `data/input/<unit>/pack/open_box.jpg`: the product as sold. Pack checks it, and Returns takes it as its reference photo
  from Pack's record.
- `data/input/<unit>/returns/1.jpg`: the returned item. Returns compares it with the reference.
- Order rows: `data/input/pack_orders.csv`, `data/input/returns_orders.csv`; cases: `data/input/returns_photo_cases.json`.
- 8 units carry a Gemini answer recorded from a real model run on these photos (`agents/returns/cassettes/`); 2 have none
  and are judged live when a Gemini key is set.

Images were downloaded on 2026-10-09 and resized to at most 1024 px.

## Units and Gemini's recorded answers

| Unit | Sold (Pack photo) | Returned (Returns photo) | Gemini identity | Disposition |
|---|---|---|---|---|
| UNIT-C26RM-012 | Samsung Galaxy Tab S9 | an Apple MacBook Pro 16 | FAIL | dispose |
| UNIT-C26RM-015 | Dell XPS 13 2017 | a Lenovo ThinkPad X1 Carbon | FAIL | dispose |
| UNIT-C26RM-022 | Canon EOS R6 Mark II | a Canon EOS 5D Mark IV | FAIL | dispose |
| UNIT-C26RM-031 | PlayStation 5 DualSense | a DualSense **Edge** (test set said "same model") | FAIL | dispose |
| UNIT-C26RM-044 | JBL **Flip 3** (test set said Flip 4) | a JBL Flip 4 | FAIL | dispose |
| UNIT-C26RM-002 | Apple iPhone 15 Pro | an iPhone 15 / 15 Plus store display | UNCERTAIN | review |
| UNIT-C26RM-001 | Apple iPhone 15 | an iPhone 15, photographed differently | UNCERTAIN | review |
| UNIT-C26RM-041 | Logitech MX Master 3S | the same mouse, photographed differently | UNCERTAIN | review |
| UNIT-C26RM-032 | PlayStation 5 console | a PlayStation 4 DualShock 4 controller | not recorded: judged live | |
| UNIT-C26RM-011 | Apple iPad Air 2 | an iPad Air 2 (the order ids conflict on purpose) | not recorded: judged live | |

The Round 2 test set labelled C26RM-031 and C26RM-044 "same model", but the Wikimedia file names below show the photos
are of different models: Gemini's FAIL is right there. Completeness is UNCERTAIN for every unit, because a product photo
cannot show the cables and accessories in the box. Recorded with `gemini-3-flash-preview` on 2026-10-09, 14 requests.

## Photo credits

| Unit | Photo | File on Wikimedia Commons | Author | Licence |
|---|---|---|---|---|
| UNIT-C26RM-001 | as sold (Pack) | [Apple iPhone 15.jpg](https://commons.wikimedia.org/wiki/File:Apple_iPhone_15.jpg) | IPHONE 15 | CC BY-SA 4.0 |
| UNIT-C26RM-001 | returned (Returns) | [Apple iPhone 15.jpeg](https://commons.wikimedia.org/wiki/File:Apple_iPhone_15.jpeg) | Ka Kit Pang | Public domain |
| UNIT-C26RM-002 | as sold (Pack) | [Apple iPhone 15 Pro.jpg](https://commons.wikimedia.org/wiki/File:Apple_iPhone_15_Pro.jpg) | IPHONE 15 | CC BY-SA 4.0 |
| UNIT-C26RM-002 | returned (Returns) | [IPhone 15 and 15 Plus in Apple Store - 2.jpg](https://commons.wikimedia.org/wiki/File:IPhone_15_and_15_Plus_in_Apple_Store_-_2.jpg) | Kyu3 | CC BY-SA 4.0 |
| UNIT-C26RM-012 | as sold (Pack) | [20230729 삼성 갤럭시 탭 S9.jpg](https://commons.wikimedia.org/wiki/File:20230729_%EC%82%BC%EC%84%B1_%EA%B0%A4%EB%9F%AD%EC%8B%9C_%ED%83%AD_S9.jpg) | Striker9498 | CC BY-SA 3.0 |
| UNIT-C26RM-012 | returned (Returns) | [Apple MacBook Pro 16" M2 Max closeup.jpg](https://commons.wikimedia.org/wiki/File:Apple_MacBook_Pro_16%22_M2_Max_closeup.jpg) | SimonWaldherr | CC BY-SA 4.0 |
| UNIT-C26RM-015 | as sold (Pack) | [DELL XPS 13 and 15 (37080596413).jpg](https://commons.wikimedia.org/wiki/File:DELL_XPS_13_and_15_%2837080596413%29.jpg) | Tinh tế Photo | CC0 |
| UNIT-C26RM-015 | returned (Returns) | [Lenovo ThinkPad X1 Carbon Ultrabook.jpg](https://commons.wikimedia.org/wiki/File:Lenovo_ThinkPad_X1_Carbon_Ultrabook.jpg) | Elroygoh | CC BY-SA 4.0 |
| UNIT-C26RM-022 | as sold (Pack) | [Canon EOS R6 Mark II - by Henry Söderlund (52546794891).jpg](https://commons.wikimedia.org/wiki/File:Canon_EOS_R6_Mark_II_-_by_Henry_S%C3%B6derlund_%2852546794891%29.jpg) | Henry Söderlund from Helsinki, Finland | CC BY 2.0 |
| UNIT-C26RM-022 | returned (Returns) | [Canon EOS 5D Mark IV (Front), 1803241116, ako.jpg](https://commons.wikimedia.org/wiki/File:Canon_EOS_5D_Mark_IV_%28Front%29%2C_1803241116%2C_ako.jpg) | Ansgar Koreng | CC BY-SA 4.0 |
| UNIT-C26RM-031 | as sold (Pack) | [Playstation DualSense Controller.png](https://commons.wikimedia.org/wiki/File:Playstation_DualSense_Controller.png) | Alex Cochrane | CC BY-SA 4.0 |
| UNIT-C26RM-031 | returned (Returns) | [DualSense Edge Controller.jpg](https://commons.wikimedia.org/wiki/File:DualSense_Edge_Controller.jpg) | Sonson2 | CC0 |
| UNIT-C26RM-041 | as sold (Pack) | [Logitech MX Master 3S HS12.jpg](https://commons.wikimedia.org/wiki/File:Logitech_MX_Master_3S_HS12.jpg) | Hayden Schiff | CC BY 4.0 |
| UNIT-C26RM-041 | returned (Returns) | [Logitech MX Master 3S HS13.jpg](https://commons.wikimedia.org/wiki/File:Logitech_MX_Master_3S_HS13.jpg) | Hayden Schiff | CC BY 4.0 |
| UNIT-C26RM-044 | as sold (Pack) | [JBL Flip 3 bluetooth speaker (DSCF2653).jpg](https://commons.wikimedia.org/wiki/File:JBL_Flip_3_bluetooth_speaker_%28DSCF2653%29.jpg) | Trougnouf | CC BY 4.0 |
| UNIT-C26RM-044 | returned (Returns) | [JBL Flip 4.jpg](https://commons.wikimedia.org/wiki/File:JBL_Flip_4.jpg) | Freekhou5 | CC BY-SA 4.0 |
| UNIT-C26RM-032 | as sold (Pack) | [Sony-PlayStation-3-2001A-wController-L.jpg](https://commons.wikimedia.org/wiki/File:Sony-PlayStation-3-2001A-wController-L.jpg) | Evan-Amos | Public domain |
| UNIT-C26RM-032 | returned (Returns) | [PS4-Console-wDS4.jpg](https://commons.wikimedia.org/wiki/File:PS4-Console-wDS4.jpg) | Evan-Amos | Public domain |
| UNIT-C26RM-011 | as sold (Pack) | [Apple iPad Air 2 vs iPad Air (15462494089).jpg](https://commons.wikimedia.org/wiki/File:Apple_iPad_Air_2_vs_iPad_Air_%2815462494089%29.jpg) | Maurizio Pesce from Milan, Italia | CC BY 2.0 |
| UNIT-C26RM-011 | returned (Returns) | [Apple iPad Air 2 vs iPad Air (15625427526).jpg](https://commons.wikimedia.org/wiki/File:Apple_iPad_Air_2_vs_iPad_Air_%2815625427526%29.jpg) | Maurizio Pesce from Milan, Italia | CC BY 2.0 |
