"use strict";
/**
 * Sandbox fixtures only — no real receipts, no real money.
 * Sandbox-shaped Daraja (M-Pesa) callback payloads for wallet adapter tests.
 * All exports are factory functions returning a fresh object on each call.
 */

function stkSuccess({ receipt = "QK12345678", amount = 1500, phone = 254798435456, date = 20261029101530, merchantRequestId = "29115-34620561-1", checkoutRequestId = "ws_CO_191220191020363925" } = {}) {
  return {
    Body: {
      stkCallback: {
        MerchantRequestID: merchantRequestId,
        CheckoutRequestID: checkoutRequestId,
        ResultCode: 0,
        ResultDesc: "The service request is processed successfully.",
        CallbackMetadata: {
          Item: [
            { Name: "Amount", Value: amount },
            { Name: "MpesaReceiptNumber", Value: receipt },
            { Name: "Balance" },
            { Name: "TransactionDate", Value: date },
            { Name: "PhoneNumber", Value: phone }
          ]
        }
      }
    }
  };
}

function stkFailed({ resultCode = 1032, resultDesc = "Request cancelled by user" } = {}) {
  return {
    Body: {
      stkCallback: {
        MerchantRequestID: "29115-34620561-1",
        CheckoutRequestID: "ws_CO_191220191020363925",
        ResultCode: resultCode,
        ResultDesc: resultDesc
      }
    }
  };
}

function stkSuccessNoMetadata({} = {}) {
  return {
    Body: {
      stkCallback: {
        MerchantRequestID: "29115-34620561-1",
        CheckoutRequestID: "ws_CO_191220191020363925",
        ResultCode: 0,
        ResultDesc: "The service request is processed successfully."
      }
    }
  };
}

function c2bSuccess({ receipt = "QK12345678", amount = "1500.00", shortcode = "600987", ref = "INV-1", phone = "254798435456", time = "20261029101530" } = {}) {
  return {
    TransactionType: "Pay Bill",
    TransID: receipt,
    TransTime: time,
    TransAmount: amount,
    BusinessShortCode: shortcode,
    BillRefNumber: ref,
    InvoiceNumber: "",
    OrgAccountBalance: "49197.00",
    ThirdPartyTransID: "",
    MSISDN: phone,
    FirstName: "John",
    MiddleName: "",
    LastName: "Doe"
  };
}

function c2bWrongAmount() {
  return c2bSuccess({ receipt: "QK20010001", amount: "2001.00" });
}

function c2bWrongDestination() {
  return c2bSuccess({ receipt: "QK88880001", shortcode: "888888" });
}

function c2bBadAmount() {
  return c2bSuccess({ receipt: "QKBAD00001", amount: "not-a-number" });
}

function malformedNull() {
  return null;
}

function malformedEmpty() {
  return {};
}

function malformedRandom() {
  return { hello: "world" };
}

module.exports = { stkSuccess, stkFailed, stkSuccessNoMetadata, c2bSuccess, c2bWrongAmount, c2bWrongDestination, c2bBadAmount, malformedNull, malformedEmpty, malformedRandom };
