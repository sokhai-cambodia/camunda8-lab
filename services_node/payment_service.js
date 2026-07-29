import express from "express";

function log(level, message) {
  const ts = new Date().toISOString().replace("T", " ").replace("Z", "");
  console.log(`${ts} ${level} ${message}`);
}

// Stand-in for a real payment microservice. Camunda knows nothing about this
// service directly -- the Charge Payment REST connector in
// bpmn/order-fulfillment.bpmn calls it over plain HTTP, same as it would call
// any existing internal API. Node/Express, sitting next to services_python/
// (order_service.py) -- proves the "any language, per step" claim rather
// than just asserting it.
const app = express();
app.use(express.json());

app.post("/charge", (req, res) => {
  const { order_id, quantity } = req.body;

  if (quantity === 10) {
    // Deliberate demo trigger: quantity=10 is the top of the DMN's in-stock
    // range (dmn/stock-check.dmn), so it still reaches Charge Payment before
    // declining here -- caught by the BPMN error boundary event via
    // errorExpression. Shows stock-check and payment authorization are
    // independent concerns: being in stock doesn't guarantee funds clear.
    log("INFO", `Declined order ${order_id}: insufficient funds`);
    return res.status(402).json({ error: "insufficient_funds" });
  }

  const amount = Math.round(quantity * 19.99 * 100) / 100;
  const paymentId = `PMT-${Math.floor(10000 + Math.random() * 90000)}`;
  log("INFO", `Charged order ${order_id}: $${amount.toFixed(2)} (${paymentId})`);
  res.json({ payment_id: paymentId, amount_charged: amount });
});

const port = process.env.PORT || 8001;
app.listen(port, () => {
  log("INFO", `Payment service (Node/Express) listening on :${port}`);
});
