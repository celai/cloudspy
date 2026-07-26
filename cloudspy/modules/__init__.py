from .accounts import AccountFinderModule
from .breach import BreachCheckModule
from .dossier import TargetDossierModule
from .email_finder import EmailFinderModule
from .footprint import FootprintModule
from .github import GitHubModule
from .hudsonrock import HudsonRockModule
from .snapchat import SnapchatModule
from .tiktok import TikTokRegionModule
from .username import UsernameSearchModule


def load_modules():
    return [
        UsernameSearchModule(),
        AccountFinderModule(),
        BreachCheckModule(),
        SnapchatModule(),
        TikTokRegionModule(),
        HudsonRockModule(),
        GitHubModule(),
        EmailFinderModule(),
        FootprintModule(),
        TargetDossierModule(),
    ]
