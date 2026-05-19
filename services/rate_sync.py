"""
Сервис синхронизации курса USDT→RUB.
Источники: Garantex API (основной), Binance P2P (запасной).
Обновляет settings.USDT_TO_RUB_RATE автоматически.
"""
import httpx
from loguru import logger
from config import settings


async def fetch_usdt_rub_rate() -> float | None:
    """Получить текущий курс USDT→RUB."""
    
    # 1. Попробуем Garantex (российская биржа, точный P2P курс)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://garantex.io/api/v2/otc/tickers")
            if resp.status_code == 200:
                data = resp.json()
                for ticker in data.get("data", []):
                    pair = ticker.get("id", "")
                    if pair == "usdtrub":
                        last_price = float(ticker.get("last", 0))
                        if last_price > 50:  # sanity check
                            logger.debug(f"Garantex USDT/RUB rate: {last_price}")
                            return last_price
    except Exception as e:
        logger.warning(f"Garantex rate fetch failed: {e}")
    
    # 2. Запасной: Binance P2P
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
                json={
                    "asset": "USDT",
                    "fiat": "RUB",
                    "merchantCheck": False,
                    "page": 1,
                    "payTypes": ["TinkoffNew"],
                    "tradeType": "BUY",
                    "rows": 5,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                advs = data.get("data", [])
                if advs:
                    prices = [float(a.get("adv", {}).get("price", 0)) for a in advs[:3]]
                    avg = sum(p for p in prices if p > 50) / max(1, len([p for p in prices if p > 50]))
                    if avg > 50:
                        logger.debug(f"Binance P2P USDT/RUB rate: {avg:.2f}")
                        return round(avg, 2)
    except Exception as e:
        logger.warning(f"Binance P2P rate fetch failed: {e}")
    
    return None


async def sync_usdt_rub_rate():
    """Обновить курс USDT→RUB в настройках бота."""
    rate = await fetch_usdt_rub_rate()
    if rate:
        old_rate = settings.USDT_TO_RUB_RATE
        settings.USDT_TO_RUB_RATE = rate
        if abs(rate - old_rate) > 0.5:
            logger.info(f"USDT/RUB rate updated: {old_rate} → {rate}")
        else:
            logger.debug(f"USDT/RUB rate: {rate} (no significant change)")
    else:
        logger.warning("Failed to fetch USDT/RUB rate, keeping current value")