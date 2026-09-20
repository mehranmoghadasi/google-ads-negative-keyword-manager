"""negkw — Google Ads negative keyword manager.

Three workflows in one CLI:

* ``suggest``   — mine a search-term report for wasted-spend queries and produce
                  a Google Ads Editor–ready negative list.
* ``conflicts`` — detect negatives that block your own positive keywords.
* ``audit``     — run ``suggest`` and then screen every proposed negative against
                  the live keyword set so you never ship a self-blocking negative.
"""

__version__ = "2.0.0"
__all__ = ["__version__"]
