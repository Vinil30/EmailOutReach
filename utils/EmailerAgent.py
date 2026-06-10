import resend
import os
class EmailerAgent:
    def __init__(self, email_details, recipient_email, email_from):
        self.recipient_email = recipient_email
        self.email_from = email_from
        self.email_subject = email_details.email_subject
        self.email_body = email_details.email_body
        self.email_api_key = os.environ.get("EMAIL_API_KEY")

    def SendEmail(self):
        resend.api_key = self.email_api_key
        response = resend.Emails.send(
            from_=self.email_from,
            to=self.recipient_email,
            subject=self.email_subject,
            html=self.email_body
        )

        return response

