import data.constants as c

class TimeHandler:
    def __init__(self, start_year=c.START_YEAR):
        self.day = c.DAYS_PER_TURN
        self.month_index = 0
        self.year = start_year
        
        self.months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]

    def process_time(self, amount=5):
        """Increments the day and handles overflow into months and years."""
        self.day += amount
        
        # Check for Month overflow (30 days per month)
        while self.day > 30:
            self.day -= 30
            self.month_index += 1
            
            # Check for Year overflow
            if self.month_index >= 12:
                self.month_index = 0
                self.year += 1

    def get_date_string(self):
        """Returns a formatted string for the UI."""
        month_name = self.months[self.month_index]
        return f"{self.day} {month_name}, {self.year} AD"