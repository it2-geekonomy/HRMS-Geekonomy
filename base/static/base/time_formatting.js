class TimeFormattingUtility {
    constructor() {
        // Default time format
        this.timeFormat = 'hh:mm A'; // Default to 12-hour format
    }

    setTimeFormat(format) {
        // Save the selected format to localStorage
        localStorage.setItem('selectedTimeFormat', format);
        this.timeFormat = format;
    }

    getFormattedTime(time) {
        if (localStorage.getItem('selectedTimeFormat')){

        }
        else{
            function fetchData(callback) {

                $.ajax({
                    url: '/settings/get-time-format/',
                    method: 'GET',
                    data: { csrfmiddlewaretoken: getCookie('csrftoken') },
                    success: function(response) {
                        var time_format = response.selected_format;

                        // Call the callback function and pass the value of 'time_format'
                        callback(time_format);
                    },
                });
            }

            // Use the fetchData function with a callback
            fetchData(function(time_format) {

                // If any time format is found setting it to the local storage.
                if(time_format){
                    localStorage.setItem('selectedTimeFormat', time_format);

                }
                // Setting a default time format hh:mm A
                else{
                    localStorage.setItem('selectedTimeFormat', 'hh:mm A');
                }
            });

        }
        // Use the stored time format
        const storedTimeFormat = localStorage.getItem('selectedTimeFormat') || 'hh:mm A';

        const s = (time == null ? '' : String(time)).trim();
        if (!s || s === 'None' || s === '-') {
            return s;
        }

        // Django renders TimeField as 24h (e.g. 13:07:00). Parsing only as hh:mm A was wrong
        // and produced incorrect times (e.g. approved 1:07 PM shown as 6:07 PM).
        const inputFormats = [
            'HH:mm:ss',
            'H:mm:ss',
            'HH:mm',
            'H:mm',
            'hh:mm:ss A',
            'hh:mm A',
            'h:mm:ss A',
            'h:mm A',
        ];
        const m = moment(s, inputFormats, true);
        if (m.isValid()) {
            return m.format(storedTimeFormat);
        }
        return s;
    }

    // Additional method for getting formatted time in 12-hour format
    getFormattedTime12Hour(time) {
        return this.getFormattedTime(time).replace(/^(\d{1,2}:\d{2}):\d{2}$/, '$1');
    }
}

// Create an instance of the TimeFormattingUtility
const timeFormatter = new TimeFormattingUtility();

// Retrieve the selected time format from localStorage
const storedTimeFormat = localStorage.getItem('selectedTimeFormat');

if (storedTimeFormat) {
    // If a time format is stored, set it in the utility
    timeFormatter.setTimeFormat(storedTimeFormat);
}
