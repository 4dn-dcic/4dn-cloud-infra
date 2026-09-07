variable "bucket_names" {
  description = "Actual datastore bucket outputs (or discovered legacy names); used by both portal and Foursight GACs."
  type        = map(string)
  default     = {}
}
