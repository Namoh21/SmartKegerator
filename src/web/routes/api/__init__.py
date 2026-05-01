from fastapi import APIRouter

from .auth     import router as _auth
from .taps     import router as _taps
from .kegs     import router as _kegs
from .beers    import router as _beers
from .pours    import router as _pours
from .users    import router as _users
from .status   import router as _status
from .devices  import router as _devices
from .system   import router as _system
from .settings import router as _settings

router = APIRouter(prefix="/api/v1")
router.include_router(_auth)
router.include_router(_taps)
router.include_router(_kegs)
router.include_router(_beers)
router.include_router(_pours)
router.include_router(_users)
router.include_router(_status)
router.include_router(_devices)
router.include_router(_system)
router.include_router(_settings)
