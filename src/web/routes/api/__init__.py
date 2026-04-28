from fastapi import APIRouter

from .auth    import router as _auth
from .taps    import router as _taps
from .kegs    import router as _kegs
from .beers   import router as _beers
from .pours   import router as _pours
from .users   import router as _users
from .devices import router as _devices

router = APIRouter(prefix="/api/v1")
router.include_router(_auth)
router.include_router(_taps)
router.include_router(_kegs)
router.include_router(_beers)
router.include_router(_pours)
router.include_router(_users)
router.include_router(_devices)
