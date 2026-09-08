"""Bridge Engineering Suite — Data Persistence Manager"""
import json
from pathlib import Path
from datetime import datetime

class DataManager:
    DB_PATH = Path.home() / ".bes" / "history.json"
    
    def __init__(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._load_db()
    
    def _load_db(self):
        if self.DB_PATH.exists():
            try:
                with open(self.DB_PATH, 'r', encoding='utf-8') as f:
                    self.db = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.db = self._init_db()
        else:
            self.db = self._init_db()
    
    def _init_db(self):
        return {
            "sections": [],
            "between_stations": [],
            "last_updated": datetime.now().isoformat(),
        }
    
    def _save_db(self):
        try:
            self.db["last_updated"] = datetime.now().isoformat()
            with open(self.DB_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.db, f, indent=2, ensure_ascii=False)
        except IOError:
            pass
    
    def add_section(self, section_name):
        if not section_name or not section_name.strip():
            return
        section_name = section_name.strip()
        sections = self.db.get("sections", [])
        sections = [s for s in sections if s != section_name]
        sections.insert(0, section_name)
        self.db["sections"] = sections[:50]
        self._save_db()
    
    def add_between_stations(self, between_stations):
        if not between_stations or not between_stations.strip():
            return
        between_stations = between_stations.strip()
        stations = self.db.get("between_stations", [])
        stations = [s for s in stations if s != between_stations]
        stations.insert(0, between_stations)
        self.db["between_stations"] = stations[:50]
        self._save_db()
    
    def get_sections(self):
        return self.db.get("sections", [])
    
    def get_between_stations(self):
        return self.db.get("between_stations", [])
    
    def get_recent_section(self):
        sections = self.get_sections()
        return sections[0] if sections else None
    
    def get_recent_between_stations(self):
        stations = self.get_between_stations()
        return stations[0] if stations else None
    
    def clear_history(self):
        self.db = self._init_db()
        self._save_db()

_dm = None
def get_data_manager():
    global _dm
    if _dm is None:
        _dm = DataManager()
    return _dm
