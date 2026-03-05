namespace MediaBot.Configuration;

public class PythonBackendOptions
{
    public const string Section = "PythonBackend";
    public string BaseUrl { get; set; } = "";
    public string HmacKey { get; set; } = "";
}
