import pygame
import data.constants as c
from data.io import standalone_game
from ui.navigation.screen import Screen
from ui.widgets.ui_elements import draw_pixel_panel, make_back_button
from ui.rendering.font_manager import fonts
from ui.rendering.standalone_background import StandaloneBackground
from ui.dialogs import show_person_info

CREDITS_LEFT_X = 120
STANDALONE_CREDIT_PANEL_PADDING = (24, 18)
STANDALONE_CREDIT_PANEL_COLOR = (34, 40, 52)
STANDALONE_CREDIT_PANEL_BORDER = (90, 110, 140)

# Each person may have "info" (free-text bio shown in the popup) and/or "links"
# (a list of {"text", "url"} shown as clickable lines below the info text).
# Optional "images" entries {"path", "text"} display an image beside a label;
# omitting "text" uses the image filename as its label.
# {"directory": "assets/..."} includes its PNGs; "recursive": True includes
# subfolders, and "exclude": ["file.png", "prefix_*.png"] filters them out.
# A person without info, links, or images is plain, non-clickable text.
CREDITS_DATA = [
    {
        "main_text": "Lead Developer: ",
        "people": [
            {
                "link_text": "GitGetGot415",
                "info": "Owns the repository",
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/GitGetGot415"}]
            }
        ]
    },
    {
        "main_text": "Music: ",
        "people": [
            {
                "link_text": "GitGetGot415",
                "info": (
                    "Albums Created:"
                ),
                "images": [
                        {"path": "assets/music/Greater Diplomacy 1/icon.png", "text": "Greater Diplomacy 1"},
                        {"path": "assets/music/Greater Diplomacy 2/icon.png", "text": "Greater Diplomacy 2"},
                        {"path": "assets/music/Greater Diplomacy 3/icon.png", "text": "Greater Diplomacy 3"},
                        {"path": "assets/music/Greater Diplomacy 4/icon.png", "text": "Greater Diplomacy 4"},
                        {"path": "assets/music/Greater Diplomacy 5/icon.png", "text": "Greater Diplomacy 5"},
                        {"path": "assets/music/Experimental/icon.png", "text": "Experimental"},
                ],
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/GitGetGot415"}]
            }
        ]
    },
    {
        "main_text": "GitHub Contributors: ",
        "people": [
            {
                "link_text": "litbrb",
                "info": (
                    "Added:\n"
                    "- Submarines\n"
                    "- Terrain art\n"
                    "- Icons for New Game, Load Game, Map Editor, Credits"
                ),
                "images": [
                    {"path": "assets/classic/Submarine.png"},
                    {"directory": "assets/terrains", "exclude": ["Unknown.png"]},
                    {"path": "assets/images/New Game.png"},
                    {"path": "assets/images/Load Game.png"},
                    {"path": "assets/images/Map Editor.png"},
                    {"path": "assets/images/Credits.png"},
                ],
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/litbrb"}]
            },
            {
                "link_text": "Pr1nted",
                "info": (
                    "Added:\n"
                    "- Conversion between OpenDoctrines and GD5\n"
                    "- Conversion between Unciv and GD5\n"
                    "- OJH Benchmark"
                ),
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/Pr1nted"}]
            }
        ]
    },
    {
        "main_text": "Map Makers: ",
        "people": [
            {
                "link_text": "neptune2019",
                "info": ("Maps Added:\n"
                "- Kaiserreich 1936\n"
                "- 1939 fixed schizo scenario\n"
                "- 2000\n"
                "- 2000 world\n"
                "- 1914 world (simplified)\n"
                "- 1914 world (detailed)\n"),
                "align": "left",
            },
        ]
    },
    {
        "main_text": "Unit Art: ",
        "people": [
            {
                "link_text": "hanskolmer",
                "info": "Hanskolmer unit art:",
                "images": [{"directory": "assets/hanskolmer", "recursive": True}],
                "align": "left",
            },
            {
                "link_text": "GitGetGot415",
                "info": "Classic unit art:",
                "images": [{"directory": "assets/classic", "recursive": True, "exclude": ["Submarine.png"]}],
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/GitGetGot415"}]
            },
        ]
    },
    {
            "main_text": "Army Icons: ",
            "people": [
                {
                    "link_text": "Randomly",
                    "info": "Icons Added:",
                    "images": [
                        {"path": "assets/symbols/Randomly_King.png"},
                        {"path": "assets/symbols/Randomly_Queen.png"},
                        {"path": "assets/symbols/Randomly_Rook.png"},
                        {"path": "assets/symbols/Randomly_Bishop.png"},
                        {"path": "assets/symbols/Randomly_Knight.png"},
                        {"path": "assets/symbols/Randomly_Pawn.png"},
                    ],
                    "align": "left",
                },
                {
                    "link_text": "commanderg",
                    "info": "Icons Added:",
                    "images": [
                        {"path": "assets/symbols/commanderg_Eagle.png"},
                        {"path": "assets/symbols/commanderg_HammerAndSickle.png"},
                        {"path": "assets/symbols/commanderg_WizardHat.png"},
                        {"path": "assets/symbols/commanderg_Skull.png"},
                    ],
                    "align": "left",
                },
                {
                    "link_text": "GitGetGot415",
                    "info": "Icons Added:",
                    "images": [{"directory": "assets/symbols", "exclude": ["Randomly_*.png", "commanderg_*.png"]}],
                    "align": "left",
                    "links": [{"text": "GitHub", "url": "https://github.com/GitGetGot415"}]
                },
            ]
        },
    {
        "main_text": "Tools: ",
        "people": [
            {
                "link_text": "github-advanced-security[bot]",
                "info": "Improved encryption for tournaments",
                "align": "left",
                "links": [{"text": "Docs", "url": "https://docs.github.com/en/get-started/learning-about-github/about-github-advanced-security"}]
            },
            {
                "link_text": "claude",
                "info": "Massive refactors to consolidate / organize code",
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/claude"}]
            },
            {
                "link_text": "dependabot",
                "info": "Update dependencies for conversion between OpenDoctrines and GD5",
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/dependabot"}]
            },
            {
                "link_text": "BeepBox",
                "info": "Music editor and synthesizer used for BeepBox JSON playback",
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/johnnesky/beepbox"}]
            },
            {
                "link_text": "UltraBox",
                "info": "Music editor and synthesizer used for UltraBox JSON playback",
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/ultraabox/ultrabox_typescript"}]
            },
            {
                "link_text": "PyMiniRacer",
                "info": "Embedded V8 JavaScript runtime used for native BeepBox and UltraBox playback",
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/bpcreech/PyMiniRacer"}]
            }
        ]
    }
]


class Credits(Screen):
    back_state = "MENU"

    def __init__(self, *, standalone=None, standalone_settings=None):
        super().__init__()
        self.is_standalone = standalone_game.IS_STANDALONE if standalone is None else standalone
        self.standalone_background = StandaloneBackground.from_game(standalone_settings) if self.is_standalone else None
        self.bg_color = (10, 10, 40) # Midnight Blue

        self.elements = [
            make_back_button(self.exit_screen),
        ]
        
        self.credits_list = []
        font = fonts.get("heading2")
        if self.is_standalone:
            self.standalone_credit = font.render(standalone_game.made_with_text(), True, (255, 255, 255))
            self.standalone_credit_rect = self.standalone_credit.get_rect(center=(c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2))
            padding_x, padding_y = STANDALONE_CREDIT_PANEL_PADDING
            self.standalone_credit_panel = self.standalone_credit_rect.inflate(2 * padding_x, 2 * padding_y)
        
        # Calculate positions once to avoid re-calculation in draw loop
        current_y = 150
        # A standalone game's Credits screen shows only its Greater Diplomacy 5 credit. See additional_draw.
        for item in [] if self.is_standalone else CREDITS_DATA:
            main_text = item.get("main_text", "")
            people = item.get("people", [])
            
            # Fetch width of the main text to position link text to its right
            main_w = font.size(main_text)[0] if main_text else 0
            main_rect = pygame.Rect(CREDITS_LEFT_X, current_y, main_w, font.get_height())
            
            credit_entry = {
                "main_text": main_text,
                "main_rect": main_rect,
                "people_links": []
            }
            
            current_x = main_rect.right
            for i, person in enumerate(people):
                link_text = person.get("link_text", "")
                info_text = person.get("info", "")
                links = person.get("links", [])
                images = person.get("images", [])
                align = person.get("align", "center")
                has_popup = bool(info_text or links or images)

                link_w = font.size(link_text)[0] if link_text else 0
                link_rect = pygame.Rect(current_x, current_y, link_w, font.get_height())

                credit_entry["people_links"].append({
                    "link_text": link_text,
                    "info": info_text,
                    "links": links,
                    "images": images,
                    "align": align,
                    "has_popup": has_popup,
                    "link_rect": link_rect
                })
                current_x += link_w
                
                # Add comma separator if not the last person
                if i < len(people) - 1:
                    comma_text = ", "
                    comma_w = font.size(comma_text)[0]
                    comma_rect = pygame.Rect(current_x, current_y, comma_w, font.get_height())
                    credit_entry["people_links"].append({
                        "link_text": comma_text,
                        "info": "",
                        "links": [],
                        "has_popup": False,
                        "link_rect": comma_rect
                    })
                    current_x += comma_w
                    
            self.credits_list.append(credit_entry)
            current_y += 50

    def draw_background(self, surface):
        if self.is_standalone:
            self.standalone_background.draw(surface)
        else:
            super().draw_background(surface)

    def additional_events(self, event):
        # Hook into mouse clicks to open the info popup for a clicked name
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for item in self.credits_list:
                for person in item.get("people_links", []):
                    if person["has_popup"] and person["link_text"] and person["link_rect"].collidepoint(event.pos):
                        show_person_info(person["link_text"], person["info"], person["links"], person["align"],
                                         images=person["images"])

    def additional_draw(self, surface):
        font = fonts.get("heading2")
        mouse_pos = pygame.mouse.get_pos()
        if self.is_standalone:
            draw_pixel_panel(surface, self.standalone_credit_panel, STANDALONE_CREDIT_PANEL_COLOR, STANDALONE_CREDIT_PANEL_BORDER, gradient_strength=0.25)
            surface.blit(self.standalone_credit, self.standalone_credit_rect)
        
        for item in self.credits_list:
            # Draw Main Text
            if item["main_text"]:
                text_surf = font.render(item["main_text"], True, (255, 255, 255))
                surface.blit(text_surf, item["main_rect"].topleft)

            # Draw Link Text
            for person in item.get("people_links", []):
                if person["link_text"]:
                    # Names that open the info popup
                    if person["has_popup"]:
                        is_hovered = person["link_rect"].collidepoint(mouse_pos)
                        link_color = (255, 255, 0) if is_hovered else (100, 100, 255) # Yellow on hover, Blue normal
                        text_surf = font.render(person["link_text"], True, link_color)
                        surface.blit(text_surf, person["link_rect"].topleft)

                        # Dynamic Underline for active links
                        if is_hovered:
                            pygame.draw.line(surface, link_color,
                                             (person["link_rect"].left, person["link_rect"].bottom - 2),
                                             (person["link_rect"].right, person["link_rect"].bottom - 2), 2)
                    # Non-clickable text like comma separators
                    else:
                        text_surf = font.render(person["link_text"], True, (255, 255, 255))
                        surface.blit(text_surf, person["link_rect"].topleft)
