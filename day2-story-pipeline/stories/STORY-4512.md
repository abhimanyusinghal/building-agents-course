As a returning customer I want the checkout to store my card details for one-click reorder so that I do not re-enter them every time.

## Acceptance criteria

- On the payment step, a "save this card for next time" checkbox is shown, default unchecked.
- When checked, the card details are stored with the customer profile and the next checkout offers a one-click reorder button.
- Removing a saved card from the profile page takes effect immediately.
- A saved card that has expired is flagged on the profile page and excluded from one-click reorder.

## Dependencies

- checkout-web, customer-profile service, payments provider.

## Rollback

Behind the oneClickReorder flag, default off.
