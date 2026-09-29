from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.deps import validated_address, normalize_address
from app.services.graph_engine import build_transaction_graph, expand_node_graph
from app.services.investigation import investigate

router = APIRouter(tags=["graph"])


@router.get("/api/wallet/{address}/graph")
def get_wallet_graph(address: str, db: Session = Depends(get_db)):
    """Investigation graph with traced peel hops, cluster co-spenders and illicit exposure highlighted."""
    address = validated_address(address, db)
    inv = investigate(db, address)   # cached right after /analyze
    return build_transaction_graph(db, address, investigation=inv)


@router.get("/api/wallet/{address}/graph/expand")
def expand_graph_node(
    address: str,
    root: str = Query(..., description="The original root address for the investigation"),
    db: Session = Depends(get_db),
):
    """Expand a node's neighbours for multi-hop exploration."""
    address = validated_address(address, db)
    return expand_node_graph(db, address, normalize_address(root))
