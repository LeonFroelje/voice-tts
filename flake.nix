{
  description = "Python devShells";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    nixvim = {
      url = "github:nix-community/nixvim";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nixvimModules = {
      url = "github:LeonFroelje/nixvim-modules";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      nixvim,
      nixvimModules,
    }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python3;

      # --- Dependency List ---
      apiDependencies = with python.pkgs; [
        fastapi
        uvicorn
        pydantic
        pydantic-settings
        python-dotenv
        pkgs.piper-tts # Provided by Nixpkgs
      ];

    in
    {
      packages.${system} = {
        default = python.pkgs.buildPythonApplication {
          pname = "piper-api";
          version = "0.1.0";
          pyproject = true;
          src = ./.;

          propagatedBuildInputs = apiDependencies;

          # Ensure FFmpeg is available to the application at runtime for MP3 conversion
          nativeBuildInputs = [ pkgs.makeWrapper ];
          postInstall = ''
            wrapProgram $out/bin/piper-api \
              --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.ffmpeg_7-headless ]}
          '';
        };
      };

      nixosModules.default =
        {
          config,
          lib,
          pkgs,
          ...
        }:
        let
          cfg = config.services.piper-api;
          defaultPkg = self.packages.${pkgs.system}.default;
        in
        {
          options.services.piper-api = with lib; {
            enable = mkEnableOption "Piper TTS API Server";

            package = mkOption {
              type = types.package;
              default = defaultPkg;
              description = "The Piper API package to use.";
            };

            host = mkOption {
              type = types.str;
              default = "127.0.0.1";
              description = "Hostname or IP to bind the server to.";
            };

            port = mkOption {
              type = types.int;
              default = 8080;
              description = "Port for the FastAPI server.";
            };

            modelsDir = mkOption {
              type = types.str;
              default = "/var/lib/piper-api-models";
              description = "Directory to store downloaded Piper ONNX models.";
            };
          };

          config = lib.mkIf cfg.enable {
            systemd.services.piper-api = {
              description = "Piper TTS FastAPI Service";
              wantedBy = [ "multi-user.target" ];
              after = [ "network.target" ];

              environment = {
                PIPER_HOST = cfg.host;
                PIPER_PORT = toString cfg.port;
                PIPER_MODELS_DIR = cfg.modelsDir;
                PYTHONUNBUFFERED = "1";
              };

              serviceConfig = {
                ExecStart = "${cfg.package}/bin/piper-api";

                # State Management (Stores the downloaded ONNX voices)
                StateDirectory = "piper-api-models";

                # Hardening
                DynamicUser = true;
                ProtectSystem = "strict";
                ProtectHome = true;
                PrivateTmp = true;
              };
            };
          };
        };

      devShells.${system} = {
        default =
          (pkgs.buildFHSEnv {
            name = "Python dev shell";
            targetPkgs =
              p: with p; [
                fd
                ripgrep
                (nixvimModules.lib.mkNvim [ nixvimModules.nixosModules.python ])
                python314
                python314Packages.pip
                zlib
                glib
              ];
            runScript = "zsh";
          }).env;

        uv =
          (pkgs.buildFHSEnv {
            name = "uv-shell";
            targetPkgs =
              p: with p; [
                uv
                zlib
                glib
                openssl
                stdenv.cc.cc.lib
                (nixvimModules.lib.mkNvim [ nixvimModules.nixosModules.python ])
              ];
            runScript = "zsh";

            multiPkgs = p: [
              p.zlib
              p.openssl
            ];
          }).env;
      };
    };
}
