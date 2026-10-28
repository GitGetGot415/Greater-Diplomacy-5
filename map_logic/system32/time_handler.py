import data.constants as c

class TimeHandler:
    def __init__(self, start_year=c.START_YEAR):
        self.day = c.DEFAULT_DAYS_PER_TURN
        self.month_index = 0
        self.year = start_year
        self.total_turns = 0 # Track turns since the scenario started
        
        self.months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]

    def process_time(self, amount=15):
        """Increments the day and handles overflow into months and years."""
        self.day += amount
        self.total_turns += 1
        
        # Check for Month overflow (30 days per month)
        if self.day > 30:
            added_months = (self.day - 1) // 30
            self.day = ((self.day - 1) % 30) + 1
            
            self.month_index += added_months
            
            added_years = self.month_index // 12
            self.month_index = self.month_index % 12
            
            self.year += added_years

        # Cap the year to 5 digits to prevent calculation/UI freezes
        """if self.year > 99999:
            self.year = 99999"""

        # Round up to the next 15 or 30 day turn increment
        """if self.day <= 15:
            self.day = 15
        else:
            self.day = 30"""

    def get_date_string(self):
        """Returns a formatted string for the UI."""
        month_name = self.months[self.month_index]
        return f"{self.day} {month_name}, {self.year} AD"