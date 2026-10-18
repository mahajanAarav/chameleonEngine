"""Catalogue of real platform target sizes (name -> (width, height)).

Our own guess at the hidden catalogue: standard social, video, print-ish and
IAB display sizes, spread across square, tall, wide and extreme aspect ratios.
"""

SIZES: dict[str, tuple[int, int]] = {
    # square-ish
    "Instagram Post": (1080, 1080),
    "LinkedIn Square": (1200, 1200),
    "Medium Rectangle": (300, 250),
    "Large Rectangle": (336, 280),
    # portrait
    "Instagram Portrait": (1080, 1350),
    "LinkedIn Vertical": (720, 900),
    "Pinterest Pin": (1000, 1500),
    "A4 Portrait": (1240, 1754),
    # tall / story
    "Instagram Story": (1080, 1920),
    "Half Page": (300, 600),
    "Wide Skyscraper": (160, 600),
    # landscape
    "Facebook Link Ad": (1200, 628),
    "LinkedIn Landscape": (1200, 627),
    "Twitter Post": (1600, 900),
    "YouTube Thumbnail": (1280, 720),
    "Instagram Landscape": (1080, 566),
    "A4 Landscape": (1754, 1240),
    # wide banners
    "Facebook Cover": (851, 315),
    "Twitter Header": (1500, 500),
    "Billboard": (970, 250),
    "LinkedIn Banner": (1584, 396),
    "Wide Banner": (1600, 400),
    # extreme banners
    "Leaderboard": (728, 90),
    "Mobile Banner": (300, 50),
    "Mobile Leaderboard": (320, 50),
}


def aspect(name: str) -> float:
    w, h = SIZES[name]
    return w / h
