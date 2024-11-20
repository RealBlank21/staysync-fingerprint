import sys
import logging
import mysql.connector
from pyzkfp import ZKFP2
from time import sleep
from threading import Thread
import datetime
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

mysql_url = "mysql://root:cldWscwfzqrsQIsVFeEFSIvOPjwhWhfd@junction.proxy.rlwy.net:20548/railway"

class FingerprintScanner:
    def __init__(self):
        self.logger = logging.getLogger('fps')
        fh = logging.FileHandler('logs.log')
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(fh)

        self.templates = []
        self.initialize_zkfp2()

        self.capture = None
        self.register = False
        self.fid = 1
        self.keep_alive = True
        self.user_ic = None  # Variable to store user IC

        # Initialize database connection
        self.db_connection = self.initialize_database()
        self.empty_fid_in_students()

    def initialize_zkfp2(self):
        self.zkfp2 = ZKFP2()
        self.zkfp2.Init()
        self.logger.info(f"{(i := self.zkfp2.GetDeviceCount())} Devices found. Connecting to the first device.")
        self.zkfp2.OpenDevice(0)
        self.zkfp2.Light("green")

    def initialize_database(self):
        try:
            db_config = mysql_url.split("://")[1].split("@")
            user_pass = db_config[0].split(":")
            host_port_db = db_config[1].split("/")
            host_port = host_port_db[0].split(":")  

            connection = mysql.connector.connect(
                host=host_port[0],
                user=user_pass[0],
                password=user_pass[1],
                port=int(host_port[1]),
                database=host_port_db[1]
            )
            self.logger.info("Database connection established.")
            return connection
        except mysql.connector.Error as err:
            self.logger.error(f"Error connecting to the database: {err}")
            sys.exit(1)

    def empty_fid_in_students(self):
        try:
            cursor = self.db_connection.cursor()
            # Update the fid field to NULL for all records in the student table
            sql = "UPDATE student SET fid = NULL"
            cursor.execute(sql)
            self.db_connection.commit()
            self.logger.info("All fid fields in the student table have been emptied.")
            cursor.close()
        except mysql.connector.Error as err:
            self.logger.error(f"Error emptying fid fields in student table: {err}")

    def save_fingerprint_to_db(self, fid, user_ic):
        try:
            cursor = self.db_connection.cursor()
            # Update the existing record based on user_ic
            sql = "UPDATE student SET fid = %s WHERE student_ic = %s"
            cursor.execute(sql, (fid, user_ic))
            # Check how many rows were affected
            if cursor.rowcount == 0:
                # If no rows were updated, you can choose to insert a new record or log a message
                self.logger.warning(f"No record found for Student with IC: {user_ic}. Consider inserting a new record.")
            else:
                self.logger.info(f"Fingerprint with FID: {fid} updated for Student with IC: {user_ic} in database.")
            self.db_connection.commit()
            cursor.close()
        except mysql.connector.Error as err:
            self.logger.error(f"Error updating fingerprint in database: {err}")

    def get_user_ic(self, fid):
        try:
            cursor = self.db_connection.cursor()
            sql = "SELECT student_ic FROM student WHERE fid = %s"
            cursor.execute(sql, (fid,))
            result = cursor.fetchone()
            cursor.close()
            return result[0] if result else None
        except mysql.connector.Error as err:
            self.logger.error(f"Error retrieving IC Student from database: {err}")
            return None

    def check_outing_ban(self, ic):
        try:
            cursor = self.db_connection.cursor()
            sql = "SELECT outing_ban_period FROM student WHERE student_ic = %s"
            cursor.execute(sql, (ic,))
            result = cursor.fetchone()
            cursor.close()
            return result
        except mysql.connector.Error as err:
            self.logger.error(f"Error retrieving IC Student from database: {err}")
            return None

    def is_outing_ban_expired(self, outing_ban_period):
        print(outing_ban_period)
        if outing_ban_period is None or outing_ban_period[0] is None:
            return False  # No outing ban exists

        # Extract the date from the result tuple
        outing_date = outing_ban_period[0]

        print(str(datetime.date.today()) + " or " + str(outing_date))

        # Check if today's date is greater than the outing date
        if outing_date > datetime.date.today():
            return True  # Outing ban has expired
        else:
            return False  # Outing ban is still active

    def outing_update(self, ic):
        try:
            cursor = self.db_connection.cursor()
            # First, get the current value of is_outing
            sql_select = "SELECT is_outing FROM student WHERE student_ic = %s"
            cursor.execute(sql_select, (ic,))
            result = cursor.fetchone()

            if result is None:
                self.logger.warning(f"No student found with IC: {ic}")
                return False  # No student found

            current_is_outing = result[0]

            # Toggle the value
            new_is_outing = not current_is_outing

            # Update the database with the new value
            sql_update = "UPDATE student SET is_outing = %s WHERE student_ic = %s"
            cursor.execute(sql_update, (new_is_outing, ic))
            self.db_connection.commit()  # Commit the transaction
            cursor.close()

            return True  # Successfully toggled
        except mysql.connector.Error as err:
            return False  # Indicate failure

    def get_is_outing(self, ic):
        try:
            cursor = self.db_connection.cursor()
            # Query to get the is_outing value
            sql_select = "SELECT is_outing FROM student WHERE student_ic = %s"
            cursor.execute(sql_select, (ic,))
            result = cursor.fetchone()
            cursor.close()

            if result is None:
                self.logger.warning(f"No student found with IC: {ic}")
                return None  # No student found

            is_outing_value = result[0]
            self.logger.info(f"Retrieved is_outing for IC: {ic}: {is_outing_value}")
            return is_outing_value  # Return the is_outing value
        except mysql.connector.Error as err:
            self.logger.error(f"Error retrieving outing status for IC {ic}: {err}")
            return None  # Indicate failure

    def identify_fingerprint(self, tmp):
        fid, score = self.zkfp2.DBIdentify(tmp)

        if fid:
            user_ic = self.get_user_ic(fid)  # Retrieve the user IC
            if user_ic:
                self.logger.info(f"Successfully identified the student: FID: {fid}, Student IC: {user_ic}, Score: {score}")
                print(f"Successfully identified the student: FID: {fid}, Student IC: {user_ic}, Score: {score}")

                outing_ban = self.check_outing_ban(user_ic)
                can_outing = self.is_outing_ban_expired(outing_ban)

                if not can_outing:
                    current_status = self.get_is_outing(user_ic)

                    if current_status:
                        print(f"The student with IC {user_ic} is currently OUTING.")
                    else:
                        print(f"The student with IC {user_ic} is currently NOT OUTING.")
                    
                    self.outing_update(user_ic)
                    new_status =  self.get_is_outing(user_ic)

                    if new_status:
                        print(f"The student with IC {user_ic} has now GONE OUTING.")
                    else:
                        print(f"The student with IC {user_ic} has now RETURNED from OUTING.")

                else:
                    print(f"{user_ic} is still banned from outing.")
                    self.logger.info(f"{user_ic} is still banned from outing.")

                self.zkfp2.Light('green')
            else:
                self.logger.warning(f"FID: {fid} found, but no associated Student with IC.")
        else:
            self.logger.warning("Fingerprint not recognized.")

        # Check if user wants to exit comparison mode
        exit_command = input("Type 'exit' to go back to the main menu or press Enter to continue comparison: ")
        if exit_command.lower() == 'exit':
            self.register = False  # Set register to False to indicate exiting comparison
            self.choose_mode()  # Prompt for mode selection again

    def register_fingerprint(self, tmp):
        if len(self.templates) < 3:
            if not self.templates or self.zkfp2.DBMatch(self.templates[-1], tmp) > 0:  # check if the finger is the same
                self.zkfp2.Light('green')
                self.templates.append(tmp)

                message = f"Finger {len(self.templates)} registered successfully! " + (f"{3 - len(self.templates)} presses left." if 3 - len(self.templates) > 0 else '')
                self.logger.info(message)

                if len(self.templates) == 3:
                    regTemp, regTempLen = self.zkfp2.DBMerge(*self.templates)
                    self.zkfp2.DBAdd(self.fid, regTemp)

                    # Save to database using the previously stored user IC
                    self.save_fingerprint_to_db(self.fid, self.user_ic)

                    self.templates.clear()
                    self.register = False
                    self.fid += 1

                    self.choose_mode()
            else:
                self.zkfp2.Light('red', 1)
                self.logger.warning("Different finger. Please enter the original finger!")

    def capture_handler(self):
        try:
            tmp, img = self.capture
            if self.register:
                self.register_fingerprint(tmp)
            else:
                self.identify_fingerprint(tmp)

        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            self.zkfp2.Terminate()
            exit(0)

        # release the capture
        self.capture = None

    def _capture_handler(self):
        try:
            self.capture_handler()
        except Exception as e:
            self.logger.error(e)
            self.capture = None

    def listenToFingerprints(self):
        try:
            while self.keep_alive:
                capture = self.zkfp2.AcquireFingerprint()
                if capture and not self.capture:
                    self.capture = capture
                    Thread(target=self._capture_handler, daemon=True).start()
                sleep(0.1)
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            self.zkfp2.Terminate()
            exit(0)

    def check_ic_exists(self, user_ic):
        try:
            cursor = self.db_connection.cursor()
            # Prepare the SQL query to check for the IC
            sql = "SELECT COUNT(*) FROM student WHERE student_ic = %s"
            cursor.execute(sql, (user_ic,))
            result = cursor.fetchone()
            cursor.close()
            
            # Check if the count is greater than 0
            if result[0] > 0:
                return True  # IC exists
            else:
                return False  # IC does not exist
        except mysql.connector.Error as err:
            self.logger.error(f"Error checking IC existence: {err}")
            return False  # Return False in case of error

    def choose_mode(self):
        while True:
            choice = input("Do you want to register a new fingerprint or identify an existing one? (r/i): ").lower()
            
            if choice in ['r', 'i']:
                if choice == 'r':
                    while True:  # This inner loop handles IC validation
                        self.user_ic = input("Please enter the user IC to register: ")  # Get user IC once
                        
                        if not self.check_ic_exists(self.user_ic):
                            print("Invalid IC. Does not exist. Please try again.")
                        else:
                            break  # Exit the loop if the IC is valid

                self.register = (choice == 'r')
                print("Press down gently on the fingerprint scanner.")
                break  # Exit the outer loop when a valid choice is made
            else:
                print("Invalid choice. Please enter 'r' to register or 'i' to identify.")

if __name__ == "__main__":
    fingerprint_scanner = FingerprintScanner()
    fingerprint_scanner.choose_mode()  # Prompt for mode selection
    fingerprint_scanner.listenToFingerprints()

