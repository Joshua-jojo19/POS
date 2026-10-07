# Harbor & Bean Café POS — Local API Demo

This demo shows how the POS page connects to a backend. The Python server serves the page, exposes JSON API endpoints, and saves menu items and completed orders in a local SQLite database.

## Run it

1. Install Python 3.10 or later if it is not already installed.
2. Extract this ZIP to a folder.
3. Open a terminal in that folder and run:

   ```bash
   python3 server.py
   ```

   On Windows, use `py server.py` if `python3` is not recognized.

4. Open `http://127.0.0.1:8000` in your browser.
5. Add menu items, choose dine-in or takeaway, and complete a demo sale. Orders are saved in `cafe_pos.db` in the same folder. Press Ctrl+C in the terminal to stop the server.

The server binds to `127.0.0.1` by default, which keeps this demo on your computer.

## API endpoints

- `GET /api/health` — check that the API is running.
- `GET /api/menu` — retrieve active menu items.
- `GET /api/orders?limit=50` — retrieve recent saved orders.
- `POST /api/orders` — create an order and record the selected payment method.

Example request body for `POST /api/orders`:

```json
{
  "order_type": "dinein",
  "table_name": "Table 2",
  "payment_method": "Cash",
  "items": [
    { "menu_item_id": "espresso", "quantity": 2 }
  ]
}
```

The backend looks up prices from its menu database and calculates the total. The dine-in service charge is a demo 5% setting in `server.py` (`SERVICE_RATE`). Menu data is seeded on the first start; edit the `MENU` list in `server.py` before starting with a fresh database to change the sample menu.

## Important demo limits

- Payment options only record a demo payment method. No card is charged, and no payment provider is connected.
- This local server has no user sign-in, production security controls, or cloud database. Do not expose it to the public internet or use it for real customer transactions.
- The next production stage should add authentication and role permissions, move data to Azure SQL, configure HTTPS and backups, and integrate a supported payment provider.
