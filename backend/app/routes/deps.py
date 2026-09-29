from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import AddressTx, Transaction
from app.utils import is_valid_btc_address, is_demo_address


def normalize_address(address: str) -> str:
    address = (address or "").strip()
    if address.lower().startswith("bc1") and not is_demo_address(address):
        address = address.lower()
    return address


def validated_address(address: str, db: Session) -> str:
    """Accept real mainnet addresses and seeded demo scenarios; reject everything else."""
    address = normalize_address(address)
    if is_valid_btc_address(address):
        return address
    if is_demo_address(address):
        known = (db.query(AddressTx.id).filter(AddressTx.address == address).first()
                 or db.query(Transaction.id).filter((Transaction.from_address == address) |
                                                    (Transaction.to_address == address)).first())
        if known:
            return address
        raise HTTPException(status_code=404, detail="Demo scenario not found. Seed it with: python seed_data.py")
    raise HTTPException(
        status_code=400,
        detail="Invalid Bitcoin address (checksum failed). Expected a mainnet P2PKH (1...), P2SH (3...) "
               "or SegWit/Taproot (bc1...) address.",
    )
